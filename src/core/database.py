"""Database connection and session management.

Supports multiple database backends:
- PostgreSQL: Local development and staging
- Databricks Lakebase: Production on Databricks Apps
"""
import logging
import os
from contextlib import contextmanager
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()


def _get_database_url() -> str:
    """
    Determine database URL based on environment.

    Priority:
    1. DATABASE_URL environment variable (explicit override)
    2. LAKEBASE_INSTANCE (Lakebase on Databricks Apps)
    3. Default local PostgreSQL

    Returns:
        Database connection URL string
    """
    # Check for explicit DATABASE_URL first
    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        return explicit_url

    # Check for Lakebase environment
    lakebase_instance = os.getenv("LAKEBASE_INSTANCE")

    if lakebase_instance:
        # Running on Databricks Apps with Lakebase
        logger.info(f"Detected Lakebase environment (instance: {lakebase_instance})")
        # Import here to avoid circular dependency
        from src.core.lakebase import get_lakebase_connection_url

        schema = os.getenv("LAKEBASE_SCHEMA", "app_data")
        user = os.getenv("PGUSER")  # May be set by Databricks Apps

        return get_lakebase_connection_url(
            instance_name=lakebase_instance,
            user=user,
            schema=schema,
        )

    # Default to local PostgreSQL for development
    return "postgresql://localhost/ai_slide_generator"


def _create_engine():
    """Create SQLAlchemy engine based on database configuration.

    Returns:
        Engine configured for the appropriate database backend
    """
    database_url = _get_database_url()
    sql_echo = os.getenv("SQL_ECHO", "false").lower() == "true"

    # All backends use PostgreSQL-compatible connections
    # (Lakebase is PostgreSQL-compatible)
    logger.info("Configuring database connection")

    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=sql_echo,
    )


# Create engine (lazy initialization to allow environment setup)
_engine = None


def get_engine():
    """Get or create the database engine."""
    global _engine
    if _engine is None:
        _engine = _create_engine()
    return _engine


# Session factory (lazy initialization)
_session_local = None


def get_session_local():
    """Get or create the session factory."""
    global _session_local
    if _session_local is None:
        _session_local = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _session_local


# Base class for models
Base = declarative_base()

# Backwards compatibility aliases
engine = property(lambda self: get_engine())
SessionLocal = property(lambda self: get_session_local())


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI routes.
    Yields database session and ensures cleanup.
    """
    session_factory = get_session_local()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.
    Use in standalone scripts and services.
    """
    session_factory = get_session_local()
    db = session_factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """Create all tables in the database."""
    Base.metadata.create_all(bind=get_engine())
