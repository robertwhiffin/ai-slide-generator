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

# Database URL from environment
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://localhost/ai_slide_generator"  # Default to PostgreSQL for local development
)


def _create_engine():
    """Create SQLAlchemy engine based on DATABASE_URL.

    Returns:
        Engine configured for the appropriate database backend
    """
    sql_echo = os.getenv("SQL_ECHO", "false").lower() == "true"

    if DATABASE_URL.startswith("databricks://"):
        # Databricks Lakebase configuration
        # Requires databricks-sql-connector
        logger.info("Configuring Databricks Lakebase connection")
        return create_engine(
            DATABASE_URL,
            echo=sql_echo,
            # Databricks SQL connector handles connection pooling
        )
    elif DATABASE_URL.startswith("postgresql"):
        # PostgreSQL configuration
        logger.info("Configuring PostgreSQL connection")
        return create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            echo=sql_echo,
        )


# Create engine
engine = _create_engine()

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for schemas
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI routes.
    Yields database session and ensures cleanup.
    """
    db = SessionLocal()
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
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """Create all tables (for development only)."""
    Base.metadata.create_all(bind=engine)

