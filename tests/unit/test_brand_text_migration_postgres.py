"""The brand-text column migrations must CONVERGE on real PostgreSQL.

These assertions cannot be made on SQLite. Every one of the brand-text
migrations returns early there (declared VARCHAR length is unenforced and
``ALTER COLUMN TYPE`` does not exist), so a SQLite test exercises none of the
decision logic — which is precisely how the defect below survived a green suite.

THE DEFECT. Two obsolete wideners (``design_system_token.name`` 100 -> 255 and
``.group`` 50 -> 255) are superseded by
:func:`~src.core.database._migrate_uncap_brand_text_columns`, which converts the
same columns to unbounded ``TEXT``. But the wideners treated "no length" (i.e.
already ``TEXT``, the WIDEST possible state) as "needs widening" and issued
``ALTER COLUMN TYPE VARCHAR(255)`` — a NARROWING of a column the newer migration
had just uncapped. The two then fought each other on alternate runs, so the
schema OSCILLATED instead of converging:

    fresh database:  create_all -> text ; run 1 -> varchar(255) ; run 2 -> text
    legacy database: run 1 -> text ; run 2 -> varchar(255) ; run 3 -> text

Two things made it worse than churn. The uncap migration read column types from
the SHARED inspector, whose reflection cache still described the pre-ALTER state,
so it SKIPPED the columns the widener had just narrowed. And once real data longer
than 255 characters existed — which the uncap migration exists to allow — the
narrowing ALTER raised ``StringDataRightTruncation`` out of an UNCAUGHT
``begin_nested()``, aborting the outer migration transaction: a hard boot failure
on a database holding legitimate brand tokens.

So the invariants under test are convergence, fixpoint-ness, and containment:

* from ANY starting width (fresh ``create_all``, varchar(50), varchar(100),
  varchar(255)) every brand-text column is ``TEXT`` after EVERY run;
* running the migration N times is a fixpoint, not an oscillation;
* a stored 5000-character token cannot make a later run raise, cannot abort the
  rest of the run, and survives byte-for-byte.

GATING. These tests are skipped unless a real PostgreSQL is reachable, so they
are inert in CI where none exists. Point ``TELLR_TEST_POSTGRES_URL`` at a
throwaway database to run them; absent that, a local default is probed and the
module skips if it does not answer. Each test creates and drops its own uniquely
named database, so runs never collide and nothing is left behind.

All fixtures SYNTHETIC (invented token names, dummy values).
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import (
    _BRAND_TEXT_COLUMNS,
    Base,
    _run_migrations,
)

pytestmark = pytest.mark.postgres

#: Admin URL used to CREATE/DROP the throwaway per-test databases. Overridable so
#: the suite can be pointed at any disposable server.
_ADMIN_URL = os.environ.get(
    "TELLR_TEST_POSTGRES_URL",
    "postgresql+psycopg2://localhost:5432/postgres",
)

#: Longer than every historical cap (50/100/255) and than the 2704-byte btree
#: index-tuple maximum is NOT approached by it — this is a token, not a DS name.
_LONG_VALUE_CHARS = 5000


def _postgres_available() -> bool:
    """True when the admin URL answers, so the module can gate itself."""
    try:
        engine = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


if not _postgres_available():  # pragma: no cover - environment-dependent
    pytest.skip(
        f"no PostgreSQL reachable at {_ADMIN_URL}; set TELLR_TEST_POSTGRES_URL to run "
        "the brand-text migration convergence suite",
        allow_module_level=True,
    )


@pytest.fixture()
def pg_engine():
    """A fresh, empty PostgreSQL database, dropped when the test finishes."""
    db_name = f"tellr_migr_{uuid.uuid4().hex[:16]}"
    admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    url = make_url(_ADMIN_URL).set(database=db_name)
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            # Terminate stragglers so the DROP cannot be blocked by a leftover
            # backend, then remove the throwaway database.
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin.dispose()


def _create_all(engine) -> None:
    """Provision the schema the way a fresh install does."""
    Base.metadata.create_all(bind=engine)


def _legacy_narrow(engine, *, group_length: int, name_length: int) -> None:
    """Rewind the two token columns to a pre-migration (legacy) width.

    Simulates a database an EARLIER deploy provisioned, which is the state the
    wideners were written for and the only state in which they should ever act.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE design_system_token "
                f'ALTER COLUMN "group" TYPE VARCHAR({group_length})'
            )
        )
        conn.execute(
            text(
                "ALTER TABLE design_system_token "
                f"ALTER COLUMN name TYPE VARCHAR({name_length})"
            )
        )


def _column_types(engine) -> dict[tuple[str, str], object]:
    """Reflect the LIVE length of every brand-text column (``None`` == TEXT)."""
    inspector = inspect(engine)
    live: dict[tuple[str, str], object] = {}
    for table_name, column_name in _BRAND_TEXT_COLUMNS:
        for column in inspector.get_columns(table_name):
            if column["name"] == column_name:
                live[(table_name, column_name)] = getattr(
                    column.get("type"), "length", None
                )
    return live


def _assert_all_text(engine, *, run: int) -> None:
    """Every brand-text column must be unbounded TEXT (no length) after *run*."""
    lengths = _column_types(engine)
    assert lengths, "no brand-text columns were reflected"
    narrowed = {key: length for key, length in lengths.items() if length is not None}
    assert not narrowed, (
        f"after migration run {run} these brand-text columns are NOT unbounded "
        f"TEXT: {narrowed}"
    )


def _insert_design_system(conn, *, name: str) -> int:
    """Insert a LIVE parent design system and return its id.

    Boolean NOT NULL flags are discovered from the live table rather than listed,
    so the helper does not have to be re-edited every time the model gains one.

    ``is_active`` is the ONE exception to the blanket FALSE, and it is load-bearing
    here rather than cosmetic. Name uniqueness is a PARTIAL unique index over
    ``WHERE is_active``, so an INACTIVE row has no index entry at all — and
    therefore no btree index-tuple size limit to overflow. Inserting a tombstone
    would have silently stopped exercising the very index whose 2704-byte limit
    these tests are about: the unindexable name would just store, and the
    translator assertion would never see the database's error.

    Every production writer creates ACTIVE rows (import/create set
    ``is_active=True``; the soft DELETE only flips an already-indexed row), so TRUE
    is also the faithful shape.
    """
    inspector = inspect(conn)
    required: list[tuple[str, str]] = []
    for column in inspector.get_columns("design_system"):
        if column["nullable"] or column["name"] in (
            "id",
            "name",
            "created_at",
            "updated_at",
        ):
            continue
        if column["name"] == "is_active":
            required.append(("is_active", "TRUE"))
            continue
        # Literal typed to the column so the INSERT is valid whatever NOT NULL
        # bookkeeping columns the model carries (booleans, the integer version).
        affinity = str(column.get("type")).upper()
        required.append((column["name"], "FALSE" if "BOOL" in affinity else "0"))
    columns = ", ".join(["name", "created_at", "updated_at", *(c for c, _ in required)])
    values = ", ".join([":name", "NOW()", "NOW()", *(v for _, v in required)])
    return conn.execute(
        text(f"INSERT INTO design_system ({columns}) VALUES ({values}) RETURNING id"),
        {"name": name},
    ).scalar_one()


def test_fresh_database_stays_text_across_repeated_migration_runs(pg_engine):
    """A fresh ``create_all`` database must not be NARROWED by any run.

    The columns start as ``TEXT`` (the ORM declares ``Text``), which is the
    widest state there is. Three consecutive runs must leave them there.
    """
    _create_all(pg_engine)
    _assert_all_text(pg_engine, run=0)

    for run in (1, 2, 3):
        _run_migrations(pg_engine)
        _assert_all_text(pg_engine, run=run)


@pytest.mark.parametrize(
    ("group_length", "name_length"),
    [(50, 100), (255, 255)],
    ids=["legacy-50-100", "legacy-255-255"],
)
def test_legacy_narrow_database_converges_to_text_and_stays(
    pg_engine, group_length, name_length
):
    """From any legacy width, every run must END at unbounded TEXT.

    The first run legitimately widens; every run after it must be a fixpoint. The
    oscillation showed up on run 2, which is why three runs are asserted.
    """
    _create_all(pg_engine)
    _legacy_narrow(pg_engine, group_length=group_length, name_length=name_length)

    for run in (1, 2, 3):
        _run_migrations(pg_engine)
        _assert_all_text(pg_engine, run=run)


def test_migration_after_long_token_is_stored_neither_raises_nor_truncates(pg_engine):
    """The killer case: a 5000-char token must not break a later migration run.

    Once the uncap migration has done its job, a token far longer than any old
    cap can legitimately be stored. A subsequent run must not attempt a narrowing
    that would raise ``StringDataRightTruncation`` — and must not abort, because
    the whole migration shares one transaction, so an escaping error is a boot
    failure.
    """
    _create_all(pg_engine)
    # The state a deploy reaches once the uncap migration has done its job: the
    # columns really are unbounded, so a long token is legitimately storable. Set
    # explicitly rather than via a migration run, so this test isolates
    # CONTAINMENT (a later run must not choke on the data) from CONVERGENCE (the
    # other tests) and stays meaningful whatever run 1 does.
    with pg_engine.begin() as conn:
        conn.execute(
            text('ALTER TABLE design_system_token ALTER COLUMN "group" TYPE TEXT')
        )
        conn.execute(
            text("ALTER TABLE design_system_token ALTER COLUMN name TYPE TEXT")
        )

    long_name = "fs-" + ("x" * (_LONG_VALUE_CHARS - 3))
    long_group = "g" * _LONG_VALUE_CHARS
    long_value = "v" * _LONG_VALUE_CHARS
    assert len(long_name) == _LONG_VALUE_CHARS

    with pg_engine.begin() as conn:
        design_system_id = _insert_design_system(conn, name="Synthetic Brand")
        conn.execute(
            text(
                'INSERT INTO design_system_token (design_system_id, "group", name, value) '
                "VALUES (:ds, :group, :name, :value)"
            ),
            {
                "ds": design_system_id,
                "group": long_group,
                "name": long_name,
                "value": long_value,
            },
        )

    # Must not raise: this is the production boot path on a database that already
    # holds long brand tokens.
    _run_migrations(pg_engine)
    _assert_all_text(pg_engine, run=1)

    # And the stored row must be intact, byte for byte.
    with pg_engine.connect() as conn:
        stored_group, stored_name, stored_value = conn.execute(
            text(
                'SELECT "group", name, value FROM design_system_token '
                "WHERE design_system_id = :ds"
            ),
            {"ds": design_system_id},
        ).one()
    assert stored_name == long_name
    assert stored_group == long_group
    assert stored_value == long_value


def test_a_failing_column_does_not_abort_the_rest_of_the_migration(pg_engine):
    """A single problem column must never prevent app startup.

    A brand-text column is made un-ALTERable (a dependent view pins its type), so
    its conversion necessarily fails. The run must still complete and convert
    every OTHER column — containment, not all-or-nothing.
    """
    _create_all(pg_engine)
    # Narrow one column and pin it with a view so ALTER TYPE on it must fail.
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE design_system_template "
                "ALTER COLUMN entry_path TYPE VARCHAR(100)"
            )
        )
        conn.execute(
            text(
                "CREATE VIEW pinned_entry_path AS "
                "SELECT entry_path FROM design_system_template"
            )
        )
    _legacy_narrow(pg_engine, group_length=50, name_length=100)

    # Must not raise even though one column cannot be converted.
    _run_migrations(pg_engine)

    lengths = _column_types(pg_engine)
    still_narrow = {key: length for key, length in lengths.items() if length is not None}
    # Only the view-pinned column may remain narrow; everything else converged.
    assert still_narrow == {("design_system_template", "entry_path"): 100}, (
        "a single un-convertible column must not stop the others: " f"{still_narrow}"
    )


def test_an_unindexable_design_system_name_fails_as_a_clear_4xx_not_a_500(pg_engine):
    """A name too large for the UNIQUE btree must be a clear 4xx, not an opaque 500.

    ``design_system.name`` carries a UNIQUE constraint, and a unique btree index
    tuple cannot exceed 2704 bytes, so an INCOMPRESSIBLE name of ~2692+ bytes raises
    ``ProgramLimitExceeded``:

        index row size 5016 exceeds btree version 4 maximum 2704
        for index "design_system_name_key"

    It fails LOUDLY and never truncates, which is the right direction. But it landed
    in the import route's generic ``except Exception`` and surfaced as
    **HTTP 500 "Failed to import design system"** — a message that tells the user
    nothing about what to change, for what is a legitimate upload. A 500 here is a
    bug, so the service raises the error type the routes map to a 4xx, with a message
    naming the real limit.

    This test originally drove a PREDICTOR (``_guard_indexable_name``, which ran
    ``zlib.compress`` as a stand-in for pglz and decided in advance). The prediction
    was unsound — a btree key is not pglz-compressed into the index, so a 2700-byte
    name passed the guard and Postgres rejected it anyway — and it was removed. The
    invariant under test is unchanged; what produces it is now REACTIVE, so the test
    drives the translator with the database's own error. Per-route coverage on all
    three write paths lives in
    ``test_design_system_name_index_limit_postgres.py``.
    """
    import random
    import string

    from src.services.design_system_service import (
        DesignSystemNameTooLongError,
        translate_name_index_limit_error,
    )

    _create_all(pg_engine)

    # Genuinely incompressible text, seeded so the case is deterministic. A PATTERNED
    # string will not do: an arithmetic sequence over the alphabet compresses to ~256
    # bytes, so Postgres really does store it and nothing should be raised.
    alphabet = string.ascii_letters + string.digits
    rng = random.Random(7)
    unindexable = "".join(rng.choice(alphabet) for _ in range(4000))
    compressible = "A" * 4000

    # A compressible name of the SAME length is stored, byte for byte, because
    # Postgres really does hold it — no code may turn away a name the database keeps.
    with pg_engine.begin() as conn:
        design_system_id = _insert_design_system(conn, name=compressible)
    with pg_engine.connect() as conn:
        stored = conn.execute(
            text("SELECT name FROM design_system WHERE id = :id"),
            {"id": design_system_id},
        ).scalar_one()
    assert stored == compressible, "the compressible name must store exactly"

    # The incompressible one is refused by the DATABASE — the authority on the
    # question — and that real error is what gets translated.
    with pytest.raises(Exception) as db_error:  # ProgramLimitExceeded
        with pg_engine.begin() as conn:
            _insert_design_system(conn, name=unindexable)
    assert "index row size" in str(db_error.value), (
        f"the fixture must be a name Postgres cannot index: {db_error.value}"
    )

    with pytest.raises(DesignSystemNameTooLongError) as excinfo:
        translate_name_index_limit_error(db_error.value, name=unindexable)

    message = str(excinfo.value)
    assert "name" in message.lower()
    # Actionable: says it is too long and gives the bound the user must get under.
    assert "2692" in message or "too long" in message.lower()

    # An UNRELATED database error must pass straight through untouched, or this
    # translation would mislabel every other failure as a naming problem.
    translate_name_index_limit_error(
        ValueError("some entirely unrelated failure"), name=unindexable
    )
