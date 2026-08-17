"""An UNSET ``agent_config`` must be SQL NULL, or the startup backfill skips the row.

``migrate_profiles`` selects the rows it has to fill with ``agent_config.is_(None)``
— SQL ``IS NULL``. The JSON scalar ``null`` is NOT SQL NULL: it is a stored value
that happens to mean "nothing", so a row holding it is invisible to that predicate
while looking empty to every reader that goes through the ORM attribute (both
deserialize to Python ``None``).

That gap is how adopting ``NormalizedAgentConfig`` on these two columns changed
behaviour with no test noticing. ``sqlalchemy.JSON`` defaults to
``none_as_null=False``, which serializes a bound ``None`` to the two-byte document
``null`` rather than leaving it as SQL NULL — so a freshly seeded ``default``
profile stopped being backfilled, never inherited its ``selected_slide_style_id``
or its two prompt strings, and therefore compared BYTE-IDENTICALLY to a brand-new
session. The first "save this session as a profile" from an untouched session got a
legitimate 409 naming ``'default'``.

The invariant these tests pin is therefore BOTH halves, because either alone is
satisfied by the broken code:

1. a row inserted WITHOUT ``agent_config`` holds SQL NULL; and
2. ``migrate_profiles`` then actually fills it.

Half 1 is measured at the DRIVER level — ``IS NULL`` in SQL, plus the raw
``agent_config`` value — never by reading the ORM attribute or by parsing the
column with ``json.loads``. Both of those launder the distinction away: the JSON
scalar ``null`` comes back as Python ``None`` exactly like SQL NULL, so a test
written that way passes on the broken code. The sibling suite
``test_style_exclusivity_persistence_boundary.py`` did precisely that.

All fixtures SYNTHETIC (invented ids, names and prompt text).
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register every model with Base.metadata
from src.core.database import Base
from src.database.models.profile import ConfigProfile
from src.database.models.prompts import ConfigPrompts
from src.database.models.session import UserSession
from src.database.models.slide_style_library import SlideStyleLibrary

_CUSTOM_SYSTEM_PROMPT = "Synthetic system prompt, deliberately unlike the default."
_CUSTOM_EDITING_INSTRUCTIONS = "Synthetic editing instructions, also unlike the default."


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
def session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


def _is_sql_null(engine, table, row_id):
    """Whether the DATABASE holds SQL NULL — the predicate the migration selects on.

    Asked in SQL rather than in Python because Python cannot see the difference:
    the JSON scalar ``null`` and SQL NULL both arrive as ``None``.
    """
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text(f"SELECT agent_config IS NULL FROM {table} WHERE id = :id"),
                {"id": row_id},
            ).scalar()
        )


def _raw(engine, table, row_id):
    """The stored value exactly as the driver hands it back, unparsed."""
    with engine.connect() as conn:
        return conn.execute(
            text(f"SELECT agent_config FROM {table} WHERE id = :id"), {"id": row_id}
        ).scalar()


def _seed_profile_like_init_default_profile(db):
    """A ``default`` profile built the way ``init_default_profile`` builds it.

    The point of the reconstruction is what it does NOT do: it never mentions
    ``agent_config``. The style lives in ``config_prompts.selected_slide_style_id``
    and only the backfill turns it into ``agent_config['slide_style_id']``.
    """
    style = SlideStyleLibrary(
        name="Synthetic Seeded Style",
        style_content="/* synthetic */",
        is_system=True,
        is_default=True,
        created_by="system",
        updated_by="system",
    )
    db.add(style)
    db.flush()

    profile = ConfigProfile(
        name="default",
        description="Default configuration profile",
        is_default=True,
        created_by="system",
        updated_by="system",
    )
    db.add(profile)
    db.flush()

    db.add(
        ConfigPrompts(
            profile_id=profile.id,
            selected_slide_style_id=style.id,
            system_prompt=_CUSTOM_SYSTEM_PROMPT,
            slide_editing_instructions=_CUSTOM_EDITING_INSTRUCTIONS,
        )
    )
    db.commit()
    return profile.id, style.id


class TestAnUnsetAgentConfigIsSqlNull:
    """Half 1: the column must hold SQL NULL, not the JSON scalar ``null``."""

    @pytest.mark.parametrize(
        ("model", "table", "kwargs"),
        [
            (ConfigProfile, "config_profiles", {"name": "Synthetic Unset Profile"}),
            (UserSession, "user_sessions", {"session_id": "synthetic-unset-session"}),
        ],
        ids=["config_profiles", "user_sessions"],
    )
    def test_a_row_inserted_without_agent_config_holds_sql_null(
        self, engine, db, model, table, kwargs
    ):
        row = model(**kwargs)
        db.add(row)
        db.commit()

        raw = _raw(engine, table, row.id)
        assert _is_sql_null(engine, table, row.id), (
            f"{table}.agent_config was left as the JSON scalar null "
            f"(driver returned {raw!r}), not SQL NULL. Any startup backfill that "
            "selects on IS NULL — migrate_profiles does — silently skips this row."
        )
        assert raw != "null", (
            f"{table}.agent_config stored the two-byte JSON document 'null': {raw!r}"
        )

    def test_the_migrations_own_orm_predicate_finds_the_row(self, db):
        """Pin the predicate the migration actually uses, not just equivalent SQL."""
        profile = ConfigProfile(name="Synthetic Predicate Profile")
        db.add(profile)
        db.commit()

        found = db.query(ConfigProfile).filter(ConfigProfile.agent_config.is_(None)).all()
        assert [p.id for p in found] == [profile.id], (
            "ConfigProfile.agent_config.is_(None) — the exact filter in "
            "migrate_profiles — does not match a profile that was never given an "
            "agent_config, so the backfill will never see it"
        )


class TestTheBackfillThenFillsIt:
    """Half 2: SQL NULL is only worth having because the backfill acts on it."""

    def test_migrate_profiles_backfills_a_freshly_seeded_default_profile(
        self, engine, db, session_factory
    ):
        from src.core.migrate_profiles_to_agent_config import migrate_profiles

        profile_id, style_id = _seed_profile_like_init_default_profile(db)
        assert _is_sql_null(engine, "config_profiles", profile_id), (
            "precondition: the seeded profile must start as SQL NULL, which is what "
            "makes it eligible for the backfill at all"
        )

        migrated = migrate_profiles(session_factory)

        assert migrated == 1, (
            f"migrate_profiles reported {migrated} rows migrated; the freshly seeded "
            "'default' profile was not among them"
        )

        db.expire_all()
        stored = db.get(ConfigProfile, profile_id).agent_config
        assert stored is not None, "the backfill left agent_config empty"
        assert stored["slide_style_id"] == style_id, (
            "the seeded profile did not inherit its selected_slide_style_id, so it "
            f"carries no style authority at all: {stored!r}"
        )
        assert stored["system_prompt"] == _CUSTOM_SYSTEM_PROMPT
        assert stored["slide_editing_instructions"] == _CUSTOM_EDITING_INSTRUCTIONS

    def test_the_backfilled_profile_no_longer_matches_an_empty_config(
        self, db, session_factory
    ):
        """The consequence the user actually hit: a 409 on the first profile save.

        ``save-from-session`` 409s when a stored profile's config compares equal to
        the config being saved. An unbackfilled ``default`` profile normalizes to the
        same all-defaults config a brand-new session carries, so the very first save
        from an untouched session collided with it.
        """
        from src.api.routes.profiles import _normalized_config_for_compare
        from src.core.migrate_profiles_to_agent_config import migrate_profiles

        profile_id, _ = _seed_profile_like_init_default_profile(db)
        a_brand_new_sessions_config = _normalized_config_for_compare(None)

        migrate_profiles(session_factory)

        db.expire_all()
        stored = db.get(ConfigProfile, profile_id).agent_config
        assert _normalized_config_for_compare(stored) != a_brand_new_sessions_config, (
            "the seeded 'default' profile still compares byte-identically to a "
            "brand-new session, so the first save-from-session returns 409 naming "
            "'default'"
        )
