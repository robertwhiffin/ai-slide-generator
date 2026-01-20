"""Entrypoints for Databricks Apps."""

from __future__ import annotations

import logging
import os

import uvicorn

logger = logging.getLogger(__name__)


def init_database() -> None:
    """Initialize database tables.
    
    This should be run once before starting the app to ensure all required
    tables exist. Safe to run multiple times - only creates tables that
    don't already exist.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    logger.info("Initializing database tables...")
    
    try:
        from src.core.database import init_db
        init_db()
        logger.info("Database tables initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database tables: {e}")
        raise SystemExit(1) from e


def main() -> None:
    """Start the uvicorn server."""
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    workers = int(os.getenv("UVICORN_WORKERS", "4"))
    uvicorn.run("src.api.main:app", host=host, port=port, workers=workers)


if __name__ == "__main__":
    main()
