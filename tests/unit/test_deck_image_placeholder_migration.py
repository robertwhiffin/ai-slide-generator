"""Tests for the deck placeholder rewrite migration (SDR-4437 F-TM-7).

PR #237 switched the external image identifier from the enumerable int PK to an
unguessable token, so ``substitute_image_placeholders`` now resolves
``{{image:<token>}}``. Decks saved BEFORE that change carry ``{{image:<int-id>}}``
in their stored HTML/JSON. This migration rewrites those placeholders in place,
per-image, so pre-existing decks keep rendering their embedded images.
"""
import json
import os
import tempfile
from datetime import datetime

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base
from src.core.database import (
    Base,
    _migrate_image_assets_add_token,
    _migrate_rewrite_deck_image_placeholders,
    _run_migrations,
)
from src.database.models.image import ImageAsset
from src.database.models.session import SessionSlideDeck, SlideDeckVersion, UserSession


@pytest.fixture
def sqlite_engine():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def session_factory(sqlite_engine):
    return sessionmaker(bind=sqlite_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def bare_sqlite_engine():
    """A SQLite engine with NO schema created — for building a legacy layout by hand."""
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


def _qual(t: str) -> str:
    return f'"{t}"'


def _make_image(session, image_id: int, token: str, is_active: bool = True) -> None:
    """Insert an image_assets row with a KNOWN id and token to assert against."""
    session.add(ImageAsset(
        id=image_id,
        token=token,
        filename=f"{image_id}.png",
        original_filename=f"{image_id}.png",
        mime_type="image/png",
        size_bytes=10,
        image_data=b"\x89PNG\r\n\x1a\n",
        is_active=is_active,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    ))


def _make_deck(session, session_id_str: str, deck_json: str, html_content: str | None = None) -> int:
    """Create a UserSession + its current SessionSlideDeck. Returns the deck id."""
    us = UserSession(
        session_id=session_id_str,
        created_at=datetime.utcnow(),
        last_activity=datetime.utcnow(),
        is_processing=False,
    )
    session.add(us)
    session.flush()  # assign us.id
    deck = SessionSlideDeck(session_id=us.id, deck_json=deck_json, html_content=html_content)
    session.add(deck)
    session.flush()
    return deck.id


def _make_version(session, session_id_str: str, deck_json: str) -> int:
    """Create a UserSession + one SlideDeckVersion snapshot. Returns the version id."""
    us = UserSession(
        session_id=session_id_str,
        created_at=datetime.utcnow(),
        last_activity=datetime.utcnow(),
        is_processing=False,
    )
    session.add(us)
    session.flush()
    ver = SlideDeckVersion(
        session_id=us.id,
        version_number=1,
        description="snapshot",
        deck_json=deck_json,
    )
    session.add(ver)
    session.flush()
    return ver.id


def _run_placeholder_migration(engine) -> None:
    with engine.begin() as conn:
        _migrate_rewrite_deck_image_placeholders(
            conn, inspect(conn), None, _qual, is_sqlite=True
        )


def _deck_updates_issued_by(engine, fn) -> list[str]:
    """Run ``fn`` and return the UPDATE statements it issued against deck tables.

    The migration runs on EVERY worker at EVERY startup, so once the one-time
    rewrite is done it must not re-issue the expensive per-image UPDATEs.
    """
    seen: list[str] = []

    def _before(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", _before)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _before)

    return [
        s for s in seen
        if s.lstrip().upper().startswith("UPDATE")
        and ("session_slide_decks" in s or "slide_deck_versions" in s)
    ]


def _deck_json(engine, deck_id: int) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT deck_json FROM session_slide_decks WHERE id = :id"),
            {"id": deck_id},
        ).scalar()


def _version_json(engine, ver_id: int) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT deck_json FROM slide_deck_versions WHERE id = :id"),
            {"id": ver_id},
        ).scalar()


class TestDeckImagePlaceholderMigration:
    def test_single_placeholder_rewritten_to_token(self, sqlite_engine, session_factory):
        token = "TOKa1_aa-AA"
        with session_factory() as s:
            _make_image(s, 1, token)
            deck_id = _make_deck(
                s, "sess-1",
                json.dumps({"slides": [{"html": '<img src="{{image:1}}">'}]}),
            )
            s.commit()

        _run_placeholder_migration(sqlite_engine)

        result = _deck_json(sqlite_engine, deck_id)
        assert "{{image:1}}" not in result          # no leftover int placeholder
        assert f"{{{{image:{token}}}}}" in result    # rewritten to the token

    def test_html_content_column_also_rewritten(self, sqlite_engine, session_factory):
        token = "TOKa1_aa-AA"
        with session_factory() as s:
            _make_image(s, 1, token)
            deck_id = _make_deck(
                s, "sess-1",
                deck_json=json.dumps({"slides": []}),
                html_content='<section><img src="{{image:1}}"></section>',
            )
            s.commit()

        _run_placeholder_migration(sqlite_engine)

        with sqlite_engine.connect() as conn:
            html = conn.execute(
                text("SELECT html_content FROM session_slide_decks WHERE id = :id"),
                {"id": deck_id},
            ).scalar()
        assert "{{image:1}}" not in html
        assert f"{{{{image:{token}}}}}" in html

    def test_multi_image_deck_all_placeholders_rewritten(self, sqlite_engine, session_factory):
        # Guards against the UPDATE...FROM half-rewrite pitfall: one deck row
        # referencing THREE distinct images must have ALL three rewritten.
        toks = {1: "TOK1_a", 2: "TOK2_b", 3: "TOK3_c"}
        with session_factory() as s:
            for img_id, tok in toks.items():
                _make_image(s, img_id, tok)
            deck_id = _make_deck(
                s, "sess-1",
                json.dumps({
                    "slides": [
                        {"html": '<img src="{{image:1}}">'},
                        {"html": '<img src="{{image:2}}">'},
                    ],
                    "css": "body{background:url({{image:3}})}",
                }),
            )
            s.commit()

        _run_placeholder_migration(sqlite_engine)

        result = _deck_json(sqlite_engine, deck_id)
        for img_id, tok in toks.items():
            assert f"{{{{image:{img_id}}}}}" not in result
            assert f"{{{{image:{tok}}}}}" in result

    def test_prefix_safe_ids_do_not_collide(self, sqlite_engine, session_factory):
        # {{image:1}} must not match inside {{image:11}} — the closing }} delimits it.
        with session_factory() as s:
            _make_image(s, 1, "TOK1_short")
            _make_image(s, 11, "TOK11_long")
            deck_id = _make_deck(
                s, "sess-1",
                json.dumps({"slides": [
                    {"html": '<img src="{{image:1}}"><img src="{{image:11}}">'},
                ]}),
            )
            s.commit()

        _run_placeholder_migration(sqlite_engine)

        result = _deck_json(sqlite_engine, deck_id)
        assert "{{image:1}}" not in result
        assert "{{image:11}}" not in result
        assert "{{image:TOK1_short}}" in result
        assert "{{image:TOK11_long}}" in result

    def test_unknown_id_left_unchanged(self, sqlite_engine, session_factory):
        with session_factory() as s:
            _make_image(s, 1, "TOK1_a")
            deck_id = _make_deck(
                s, "sess-1",
                json.dumps({"slides": [{"html": '<img src="{{image:999}}">'}]}),
            )
            s.commit()

        _run_placeholder_migration(sqlite_engine)

        result = _deck_json(sqlite_engine, deck_id)
        assert "{{image:999}}" in result  # no image row 999 → untouched

    def test_migration_is_idempotent(self, sqlite_engine, session_factory):
        token = "TOK1_a"
        with session_factory() as s:
            _make_image(s, 1, token)
            deck_id = _make_deck(
                s, "sess-1",
                json.dumps({"slides": [{"html": '<img src="{{image:1}}">'}]}),
            )
            s.commit()

        _run_placeholder_migration(sqlite_engine)
        first = _deck_json(sqlite_engine, deck_id)
        _run_placeholder_migration(sqlite_engine)  # second run must be a no-op
        second = _deck_json(sqlite_engine, deck_id)

        assert first == second
        assert f"{{{{image:{token}}}}}" in second

    def test_soft_deleted_image_still_rewritten(self, sqlite_engine, session_factory):
        # A deck may reference an image that was later soft-deleted; it must
        # still resolve, so the rewrite must not filter on is_active.
        token = "TOKdel_a"
        with session_factory() as s:
            _make_image(s, 1, token, is_active=False)
            deck_id = _make_deck(
                s, "sess-1",
                json.dumps({"slides": [{"html": '<img src="{{image:1}}">'}]}),
            )
            s.commit()

        _run_placeholder_migration(sqlite_engine)

        result = _deck_json(sqlite_engine, deck_id)
        assert "{{image:1}}" not in result
        assert f"{{{{image:{token}}}}}" in result

    def test_version_history_deck_json_rewritten(self, sqlite_engine, session_factory):
        token = "TOKv1_a"
        with session_factory() as s:
            _make_image(s, 1, token)
            ver_id = _make_version(
                s, "sess-1",
                json.dumps({"slides": [{"html": '<img src="{{image:1}}">'}]}),
            )
            s.commit()

        _run_placeholder_migration(sqlite_engine)

        result = _version_json(sqlite_engine, ver_id)
        assert "{{image:1}}" not in result
        assert f"{{{{image:{token}}}}}" in result

    def test_no_deck_updates_when_nothing_to_rewrite(self, sqlite_engine, session_factory):
        # The app runs this migration on EVERY worker on EVERY boot. Once the
        # one-time rewrite is done (decks hold only token placeholders), the
        # migration must short-circuit and issue NO per-image UPDATEs — otherwise
        # every worker re-scans every deck table 3x per image on each startup,
        # which stalled real multi-worker startup on prod-scale data.
        with session_factory() as s:
            # Token deliberately does NOT start with a digit, so it is not an
            # int-style placeholder on any backend.
            _make_image(s, 1, "TOKnondigit_aa")
            _make_deck(
                s, "sess-1",
                json.dumps({"slides": [{"html": '<img src="{{image:TOKnondigit_aa}}">'}]}),
            )
            s.commit()

        issued = _deck_updates_issued_by(
            sqlite_engine, lambda: _run_placeholder_migration(sqlite_engine)
        )
        assert issued == [], f"expected no deck UPDATEs on an already-migrated DB, got: {issued}"

    def test_rewrite_runs_when_token_added_in_same_run_with_shared_inspector(
        self, bare_sqlite_engine
    ):
        # Reproduces the fresh-DB/fork skip: _migrate_image_assets_add_token adds
        # the token column in the SAME migration transaction, so the shared
        # inspector _run_migrations threads through has a cached reflection with no
        # 'token'. The rewrite must reflect the LIVE schema (fresh inspector), or it
        # returns early and silently skips the rewrite on every fresh DB/fork.
        with bare_sqlite_engine.begin() as conn:
            # Legacy image_assets: NO token column yet.
            conn.execute(text(
                "CREATE TABLE image_assets (id INTEGER PRIMARY KEY, filename TEXT)"
            ))
            conn.execute(text(
                "CREATE TABLE session_slide_decks "
                "(id INTEGER PRIMARY KEY, deck_json TEXT, html_content TEXT)"
            ))
            conn.execute(text(
                "CREATE TABLE slide_deck_versions (id INTEGER PRIMARY KEY, deck_json TEXT)"
            ))
            conn.execute(text("INSERT INTO image_assets (id, filename) VALUES (1, 'a.png')"))
            conn.execute(
                text("INSERT INTO session_slide_decks (id, deck_json) VALUES (1, :d)"),
                {"d": json.dumps({"slides": [{"html": '<img src="{{image:1}}">'}]})},
            )

        with bare_sqlite_engine.begin() as conn:
            shared = inspect(conn)  # ONE inspector, exactly as _run_migrations uses
            _migrate_image_assets_add_token(conn, shared, None, _qual, is_sqlite=True)
            _migrate_rewrite_deck_image_placeholders(conn, shared, None, _qual, is_sqlite=True)

        with bare_sqlite_engine.connect() as conn:
            token = conn.execute(text("SELECT token FROM image_assets WHERE id=1")).scalar()
            deck = conn.execute(
                text("SELECT deck_json FROM session_slide_decks WHERE id=1")
            ).scalar()

        assert token  # token was backfilled
        assert "{{image:1}}" not in deck, "rewrite skipped — stale shared-inspector reflection"
        assert f"{{{{image:{token}}}}}" in deck

    def test_full_run_migrations_rewrites_placeholders(self, sqlite_engine, session_factory):
        # End-to-end: the placeholder rewrite fires as part of the full
        # _run_migrations pipeline (correct placement, after the token backfill).
        token = "TOKe2e_a"
        with session_factory() as s:
            _make_image(s, 1, token)
            deck_id = _make_deck(
                s, "sess-1",
                json.dumps({"slides": [{"html": '<img src="{{image:1}}">'}]}),
            )
            s.commit()

        _run_migrations(sqlite_engine, schema=None)

        result = _deck_json(sqlite_engine, deck_id)
        assert "{{image:1}}" not in result
        assert f"{{{{image:{token}}}}}" in result
