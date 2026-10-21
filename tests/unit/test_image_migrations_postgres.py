"""The image-token migrations on real PostgreSQL (SDR-4437 F-TM-7).

Both migrations have a PostgreSQL-only path that SQLite cannot exercise: the token
backfill is one ``UPDATE ... FROM unnest(...)``, and the deck placeholder rewrite
runs a PL/pgSQL function once per row. On a prod fork the old shapes took ~28 s
(3,408 single-row UPDATEs) and ~86 s (a 549-deep chained ``replace()`` over every
matching row), and every later boot re-scanned ~1 GB of deck blobs for nothing.

GATING. Skipped unless a real PostgreSQL is reachable at ``TELLR_TEST_POSTGRES_URL``
(CI provides one). Each test creates and drops its own uniquely named database.
All fixtures are synthetic.
"""

import json
import os
import re
import uuid

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import (
    _DECK_IMAGE_PLACEHOLDER_REWRITE,
    Base,
    _migrate_image_assets_add_token,
    _migrate_rewrite_deck_image_placeholders,
    _run_migrations,
)
from tests.unit.test_deck_image_placeholder_migration import (
    _make_deck,
    _make_image,
    _make_version,
)

pytestmark = pytest.mark.postgres

_ADMIN_URL = os.environ.get(
    "TELLR_TEST_POSTGRES_URL",
    "postgresql+psycopg2://localhost:5432/postgres",
)


def _postgres_available() -> bool:
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
        "the image migration suite",
        allow_module_level=True,
    )


@pytest.fixture()
def pg_engine():
    """A fresh PostgreSQL database with the full schema, dropped afterwards."""
    db_name = f"tellr_img_{uuid.uuid4().hex[:16]}"
    admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    engine = create_engine(make_url(_ADMIN_URL).set(database=db_name))
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin.dispose()


@pytest.fixture()
def session_factory(pg_engine):
    return sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)


def _qual(t: str) -> str:
    return f'"{t}"'


def _statements_issued_by(engine, fn) -> list[str]:
    seen: list[str] = []

    def _before(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", _before)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _before)
    return seen


def _rewrite(engine) -> None:
    with engine.begin() as conn:
        _migrate_rewrite_deck_image_placeholders(
            conn, inspect(conn), None, _qual, is_sqlite=False
        )


def _scalar(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def _ph(value) -> str:
    return f"{{{{image:{value}}}}}"


class TestTokenBackfillPostgres:
    def test_one_statement_backfills_every_row_with_a_distinct_urlsafe_token(
        self, pg_engine
    ):
        with pg_engine.begin() as conn:
            conn.execute(text("DROP TABLE image_assets CASCADE"))
            conn.execute(text(
                "CREATE TABLE image_assets (id SERIAL PRIMARY KEY, filename TEXT)"
            ))
            conn.execute(text(
                "INSERT INTO image_assets (filename) "
                "SELECT 'img-' || g || '.png' FROM generate_series(1, 50) AS g"
            ))

        def _migrate():
            with pg_engine.begin() as conn:
                _migrate_image_assets_add_token(
                    conn, inspect(conn), None, _qual, is_sqlite=False
                )

        statements = _statements_issued_by(pg_engine, _migrate)

        updates = [s for s in statements if s.lstrip().upper().startswith("UPDATE")]
        assert len(updates) == 1, f"expected one backfill UPDATE, got {len(updates)}"
        with pg_engine.connect() as conn:
            tokens = conn.execute(text("SELECT token FROM image_assets")).scalars().all()
            nullable = conn.execute(text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'image_assets' AND column_name = 'token'"
            )).scalar()
        assert len(tokens) == 50 and len(set(tokens)) == 50
        # secrets.token_urlsafe(32): 43 chars of the URL-safe alphabet.
        assert all(re.fullmatch(r"[A-Za-z0-9_-]{43}", t) for t in tokens)
        assert nullable == "NO"


class TestDeckPlaceholderRewritePostgres:
    def test_rewrites_every_column_and_every_image(self, pg_engine, session_factory):
        with session_factory() as s:
            _make_image(s, 1, "TOK1_short")
            _make_image(s, 11, "TOK11_long")
            _make_image(s, 2, "TOK2_deleted", is_active=False)
            deck_id = _make_deck(
                s, "sess-1",
                json.dumps({
                    "slides": [{"html": f'<img src="{_ph(1)}"><img src="{_ph(11)}">'}],
                    "css": f"body{{background:url({_ph(2)})}}",
                }),
                html_content=f'<img src="{_ph(1)}"><img src="{_ph(1)}">',
            )
            ver_id = _make_version(
                s, "sess-2", json.dumps({"slides": [{"html": _ph(11)}]})
            )
            s.commit()

        _rewrite(pg_engine)

        deck_json = _scalar(pg_engine, "SELECT deck_json FROM session_slide_decks WHERE id = :i", i=deck_id)
        html = _scalar(pg_engine, "SELECT html_content FROM session_slide_decks WHERE id = :i", i=deck_id)
        version = _scalar(pg_engine, "SELECT deck_json FROM slide_deck_versions WHERE id = :i", i=ver_id)
        # Prefix-safe: {{image:1}} never matched inside {{image:11}}.
        assert _ph("TOK1_short") in deck_json and _ph("TOK11_long") in deck_json
        # Soft-deleted images still resolve.
        assert _ph("TOK2_deleted") in deck_json
        assert html.count(_ph("TOK1_short")) == 2
        assert version == json.dumps({"slides": [{"html": _ph("TOK11_long")}]})
        for blob in (deck_json, html, version):
            assert not re.search(r"\{\{image:[0-9]+\}\}", blob), blob

    def test_leaves_unmappable_placeholders_unchanged(self, pg_engine, session_factory):
        # 999 has no image row; 01 is not id 1's canonical form (the old chained
        # replace never matched it either); the 25-digit id is beyond bigint and
        # must not abort the migration transaction.
        huge = "9" * 25
        with session_factory() as s:
            _make_image(s, 1, "TOK1_a")
            deck_id = _make_deck(
                s, "sess-1",
                json.dumps({"slides": [{"html": _ph(999) + _ph("01") + _ph(huge) + _ph(1)}]}),
            )
            s.commit()

        _rewrite(pg_engine)

        deck_json = _scalar(pg_engine, "SELECT deck_json FROM session_slide_decks WHERE id = :i", i=deck_id)
        assert _ph(999) in deck_json
        assert _ph("01") in deck_json
        assert _ph(huge) in deck_json
        assert _ph("TOK1_a") in deck_json

    def test_scans_each_column_once_without_a_per_image_replace_chain(
        self, pg_engine, session_factory
    ):
        with session_factory() as s:
            for image_id in range(1, 31):
                _make_image(s, image_id, f"TOK{image_id}_x")
            _make_deck(
                s, "sess-1",
                json.dumps({"slides": [{"html": "".join(_ph(i) for i in range(1, 31))}]}),
            )
            s.commit()

        statements = _statements_issued_by(pg_engine, lambda: _rewrite(pg_engine))

        deck_updates = [
            s for s in statements
            if s.lstrip().upper().startswith("UPDATE")
            and ("session_slide_decks" in s or "slide_deck_versions" in s)
        ]
        assert len(deck_updates) == 3, deck_updates
        assert all(s.count("replace(") == 0 for s in deck_updates), (
            "the per-image chained replace() is back"
        )

    def test_records_completion_and_later_boots_touch_no_deck_table(
        self, pg_engine, session_factory
    ):
        with session_factory() as s:
            _make_image(s, 1, "TOK1_a")
            _make_deck(s, "sess-1", json.dumps({"slides": [{"html": _ph(1) + _ph(999)}]}))
            s.commit()

        _rewrite(pg_engine)

        assert _scalar(
            pg_engine, "SELECT count(*) FROM data_migrations WHERE name = :n",
            n=_DECK_IMAGE_PLACEHOLDER_REWRITE,
        ) == 1
        later_boot = [
            s for s in _statements_issued_by(pg_engine, lambda: _rewrite(pg_engine))
            if "session_slide_decks" in s or "slide_deck_versions" in s
        ]
        assert later_boot == [], later_boot

    def test_leaves_no_helper_function_behind(self, pg_engine, session_factory):
        with session_factory() as s:
            _make_image(s, 1, "TOK1_a")
            _make_deck(s, "sess-1", json.dumps({"slides": [{"html": _ph(1)}]}))
            s.commit()

        _rewrite(pg_engine)

        assert _scalar(
            pg_engine,
            "SELECT count(*) FROM pg_proc WHERE proname = 'tellr_rewrite_image_placeholders'",
        ) == 0

    def test_full_run_migrations_on_a_legacy_database(self, pg_engine, session_factory):
        """A pre-token database: the backfill assigns tokens, then decks use them."""
        with session_factory() as s:
            _make_image(s, 1, "placeholder-token-1")
            _make_image(s, 2, "placeholder-token-2")
            deck_id = _make_deck(
                s, "sess-1", json.dumps({"slides": [{"html": _ph(1) + _ph(2)}]})
            )
            s.commit()
        with pg_engine.begin() as conn:
            conn.execute(text("ALTER TABLE image_assets DROP COLUMN token"))

        _run_migrations(pg_engine, schema=None)

        with pg_engine.connect() as conn:
            tokens = dict(conn.execute(text("SELECT id, token FROM image_assets")).all())
            deck_json = conn.execute(
                text("SELECT deck_json FROM session_slide_decks WHERE id = :i"), {"i": deck_id}
            ).scalar()
        assert all(re.fullmatch(r"[A-Za-z0-9_-]{43}", t) for t in tokens.values())
        assert deck_json == json.dumps(
            {"slides": [{"html": _ph(tokens[1]) + _ph(tokens[2])}]}
        )
