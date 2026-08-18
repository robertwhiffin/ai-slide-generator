"""Entrypoints for Databricks Apps."""

from __future__ import annotations

import logging
import os
import traceback

import uvicorn

logger = logging.getLogger(__name__)


def init_database(seed_databricks_defaults: bool = False) -> None:
    """Initialize database tables and seed default content.

    This should be run once before starting the app to ensure all required
    tables exist and default content is seeded. Safe to run multiple times -
    only creates tables that don't already exist, and seeding is skipped if
    content already exists.

    Args:
        seed_databricks_defaults: If True, also seed Databricks-specific content
                                  (DATABRICKS_DECK_PROMPTS, DATABRICKS_SLIDE_STYLES).
                                  If False, only seed generic content.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Log environment for debugging
    lakebase_type = os.getenv("LAKEBASE_TYPE", "not set")
    lakebase_instance = os.getenv("LAKEBASE_INSTANCE", "not set")
    lakebase_pg_host = os.getenv("LAKEBASE_PG_HOST", "not set")
    pg_host = os.getenv("PGHOST", "not set")
    pg_user = os.getenv("PGUSER", "not set")
    logger.info(
        f"Startup env: LAKEBASE_TYPE={lakebase_type}, LAKEBASE_INSTANCE={lakebase_instance}, "
        f"LAKEBASE_PG_HOST={lakebase_pg_host}, PGHOST={pg_host}, PGUSER={pg_user}"
    )

    logger.info("Initializing database tables...")

    try:
        from src.core.database import init_db
        init_db()
        logger.info("Database tables initialized successfully")
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Failed to initialize database tables: {e}\n{tb}")
        raise SystemExit(1) from e

    # Data migrations/backfills that used to run in the FastAPI lifespan now run
    # HERE, once, before the server forks its workers — the uvicorn workers must
    # never execute migration code (4 of them racing the migration chain on boot
    # wedged startup). init_db() above runs the schema/data migrations; these two
    # convert legacy profile/session rows to the agent_config shape.
    logger.info("Migrating profiles/sessions to agent_config...")
    try:
        from src.core.database import get_session_local
        from src.core.migrate_profiles_to_agent_config import (
            backfill_sessions,
            migrate_profiles,
        )
        migrated = migrate_profiles(get_session_local())
        if migrated:
            logger.info(f"Migrated {migrated} profiles to agent_config")
        backfilled = backfill_sessions(get_session_local())
        if backfilled:
            logger.info(f"Backfilled {backfilled} sessions with agent_config")
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Failed to migrate profiles/sessions to agent_config: {e}\n{tb}")
        raise SystemExit(1) from e

    # Seed default content
    logger.info(f"Seeding defaults (include_databricks={seed_databricks_defaults})...")
    try:
        from src.core.init_default_profile import seed_defaults
        seed_defaults(include_databricks=seed_databricks_defaults)
        logger.info("Default content seeded successfully")
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Failed to seed defaults: {e}\n{tb}")
        raise SystemExit(1) from e

    # Seed/load the Fernet master key pre-fork (SDR-4437 CRITICAL-3) so all
    # uvicorn workers find the encryption_keys row already present.
    logger.info("Ensuring encryption key...")
    try:
        from src.core.encryption import ensure_encryption_key
        ensure_encryption_key()
        logger.info("Encryption key ready")
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Failed to ensure encryption key: {e}\n{tb}")
        raise SystemExit(1) from e


def main() -> None:
    """Start the uvicorn server."""
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    workers = int(os.getenv("UVICORN_WORKERS", "4"))
    uvicorn.run("src.api.main:app", host=host, port=port, workers=workers)


if __name__ == "__main__":
    main()
