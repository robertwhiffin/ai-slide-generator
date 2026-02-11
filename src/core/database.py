"""Database connection and session management.

Supports multiple database backends:
- PostgreSQL: Local development and staging
- Databricks Lakebase: Production on Databricks Apps (detected via PGHOST env var)

For Lakebase connections, implements automatic OAuth token refresh to handle
token expiration (tokens expire after 1 hour). Uses SQLAlchemy's do_connect
event to inject fresh tokens for new connections.

See: https://apps-cookbook.dev/docs/fastapi/getting_started/lakebase_connection/
"""
import asyncio
import logging
import os
import time
import uuid
from contextlib import contextmanager
from typing import Generator, Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, URL
from sqlalchemy.orm import Session, declarative_base, sessionmaker

logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# =============================================================================
# Lakebase Token Management
# =============================================================================

# Global token storage for Lakebase OAuth authentication
_postgres_token: Optional[str] = None
_last_token_refresh: float = 0
_token_refresh_task: Optional[asyncio.Task] = None

# Refresh interval: 50 minutes (tokens expire after 1 hour)
TOKEN_REFRESH_INTERVAL_SECONDS = 50 * 60


def is_lakebase_environment() -> bool:
    """Check if running in a Lakebase environment (Databricks Apps).
    
    Returns:
        True if PGHOST and PGUSER are set (auto-injected by Databricks Apps)
    """
    return bool(os.getenv("PGHOST") and os.getenv("PGUSER"))


def _generate_lakebase_token() -> str:
    """Generate a fresh OAuth token for Lakebase authentication.
    
    Uses the system client (service principal) for database authentication.
    User tokens are not valid for Lakebase access.
    
    Returns:
        OAuth token string to use as PostgreSQL password
        
    Raises:
        Exception: If token generation fails
    """
    from src.core.databricks_client import get_system_client

    ws = get_system_client()
    instance_name = os.getenv("LAKEBASE_INSTANCE")

    if instance_name:
        # Generate credential for specific instance
        cred = ws.database.generate_database_credential(
            request_id=str(uuid.uuid4()),
            instance_names=[instance_name],
        )
        return cred.token
    else:
        # Fallback: use workspace authentication token
        # This works when the app has database resource attached
        token = ws.config.authenticate()
        if hasattr(token, "token"):
            return token.token
        return str(token)


def _get_lakebase_token() -> str:
    """Get the current OAuth token for Lakebase authentication.
    
    Returns the cached token if available, otherwise generates a new one.
    For production use, the token is refreshed by the background task.
    
    Returns:
        OAuth token string
    """
    global _postgres_token, _last_token_refresh
    
    # If we have a cached token, return it
    if _postgres_token is not None:
        return _postgres_token
    
    # Generate initial token
    try:
        _postgres_token = _generate_lakebase_token()
        _last_token_refresh = time.time()
        logger.info("Generated initial Lakebase OAuth token")
        return _postgres_token
    except Exception as e:
        logger.error(f"Failed to get Lakebase token: {e}")
        raise


async def _refresh_token_background() -> None:
    """Background task to refresh Lakebase OAuth tokens every 50 minutes.
    
    Tokens expire after 1 hour, so we refresh at 50 minutes to ensure
    continuous connectivity with a 10-minute buffer.
    """
    global _postgres_token, _last_token_refresh

    while True:
        try:
            await asyncio.sleep(TOKEN_REFRESH_INTERVAL_SECONDS)
            logger.info("Background token refresh: Generating fresh Lakebase OAuth token")

            _postgres_token = _generate_lakebase_token()
            _last_token_refresh = time.time()
            logger.info("Background token refresh: Token updated successfully")

        except asyncio.CancelledError:
            logger.info("Background token refresh task cancelled")
            raise
        except Exception as e:
            logger.error(f"Background token refresh failed: {e}")
            # Continue running - will retry on next interval


async def start_token_refresh() -> None:
    """Start the background token refresh task.
    
    Should be called during FastAPI lifespan startup when running
    in a Lakebase environment.
    """
    global _token_refresh_task, _postgres_token, _last_token_refresh

    if not is_lakebase_environment():
        logger.debug("Not a Lakebase environment, skipping token refresh setup")
        return

    # Generate initial token before starting background refresh
    try:
        _postgres_token = _generate_lakebase_token()
        _last_token_refresh = time.time()
        logger.info("Initial Lakebase OAuth token generated")
    except Exception as e:
        logger.error(f"Failed to generate initial Lakebase token: {e}")
        raise

    # Start background refresh task
    if _token_refresh_task is None or _token_refresh_task.done():
        _token_refresh_task = asyncio.create_task(_refresh_token_background())
        logger.info("Background token refresh task started (50-minute interval)")


async def stop_token_refresh() -> None:
    """Stop the background token refresh task.
    
    Should be called during FastAPI lifespan shutdown.
    """
    global _token_refresh_task

    if _token_refresh_task and not _token_refresh_task.done():
        _token_refresh_task.cancel()
        try:
            await _token_refresh_task
        except asyncio.CancelledError:
            pass
        logger.info("Background token refresh task stopped")


def _get_database_url() -> str:
    """
    Determine database URL based on environment.

    Priority:
    1. DATABASE_URL environment variable (explicit override)
    2. PGHOST (Lakebase on Databricks Apps - auto-set when database resource attached)
    3. Default local PostgreSQL

    For Lakebase, returns URL without password - the password is injected
    dynamically via the do_connect event to support token refresh.

    Returns:
        Database connection URL string
    """
    # Check for explicit DATABASE_URL first
    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url and not explicit_url.startswith("jdbc:"):
        return explicit_url

    # Check for Lakebase environment (PGHOST auto-set by Databricks Apps)
    pg_host = os.getenv("PGHOST")
    pg_user = os.getenv("PGUSER")

    if pg_host and pg_user:
        # Running on Databricks Apps with Lakebase
        logger.info(f"Detected Lakebase environment (PGHOST: {pg_host})")

        # Build PostgreSQL connection URL WITHOUT password
        # Password is injected dynamically via do_connect event for token refresh
        database = "databricks_postgres"
        schema = os.getenv("LAKEBASE_SCHEMA", "app_data")

        url = f"postgresql://{pg_user}@{pg_host}:5432/{database}?sslmode=require"

        # Add schema to search path
        if schema:
            url += f"&options=-csearch_path%3D{schema}"

        return url

    # Default to local PostgreSQL for development
    return "postgresql://localhost/ai_slide_generator"


def _create_engine():
    """Create SQLAlchemy engine based on database configuration.

    For Lakebase environments, registers a do_connect event listener to inject
    fresh OAuth tokens for each new connection. This supports automatic token
    refresh without recreating the engine.

    Returns:
        Engine configured for the appropriate database backend
    """
    import traceback
    database_url = _get_database_url()
    sql_echo = os.getenv("SQL_ECHO", "false").lower() == "true"
    
    # Debug: Log when engine is created and by whom
    pytest_test = os.getenv("PYTEST_CURRENT_TEST")
    logger.warning(
        f"DATABASE ENGINE CREATION: url={database_url[:50]}..., "
        f"PYTEST_CURRENT_TEST={pytest_test}, "
        f"ENVIRONMENT={os.getenv('ENVIRONMENT')}"
    )
    # Print stack trace to see what triggered engine creation
    if pytest_test or os.getenv("ENVIRONMENT") == "test":
        logger.warning(f"Engine creation stack trace:\n{''.join(traceback.format_stack()[-8:-1])}")

    logger.info("Configuring database connection")

    # Create engine with connection pooling
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=sql_echo,
    )

    # For Lakebase: register event listener to inject fresh tokens
    if is_lakebase_environment():
        @event.listens_for(engine, "do_connect")
        def provide_token(dialect, conn_rec, cargs, cparams):
            """Inject current OAuth token for new database connections."""
            global _postgres_token
            
            # Get token (generates if not yet available)
            token = _postgres_token if _postgres_token else _get_lakebase_token()
            cparams["password"] = token

        logger.info("Registered do_connect event for Lakebase token injection")

    return engine


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


def _run_migrations(engine):
    """Run schema migrations for columns/tables added after initial deployment.

    create_all() only creates NEW tables — it won't add columns to existing
    tables. This function detects missing columns and tables, then adds them
    via ALTER TABLE / CREATE TABLE using the same connection the app uses.
    """
    from sqlalchemy import text, inspect

    inspector = inspect(engine)
    schema = os.getenv("LAKEBASE_SCHEMA") or None

    # --- 1. Migrate user_sessions: add columns introduced in session-permissions ---
    table_name = "user_sessions"
    try:
        existing_cols = {
            col["name"] for col in inspector.get_columns(table_name, schema=schema)
        }
    except Exception:
        # Table doesn't exist yet — create_all() will handle it
        existing_cols = set()

    migrations = []

    if existing_cols:  # Table exists; check for missing columns
        new_columns = {
            "created_by": "VARCHAR(255)",
            "visibility": "VARCHAR(20)",
            "experiment_id": "VARCHAR(255)",
        }
        for col_name, col_type in new_columns.items():
            if col_name not in existing_cols:
                migrations.append(
                    f'ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}'
                )

    if migrations:
        logger.info(f"Running {len(migrations)} migration(s) on {table_name}")
        with engine.connect() as conn:
            for stmt in migrations:
                logger.info(f"  Migration: {stmt}")
                try:
                    conn.execute(text(stmt))
                except Exception as e:
                    logger.warning(f"  Migration skipped (may already exist): {e}")
            conn.commit()
        logger.info("Migrations complete")

    # --- 2. Ensure new tables exist (session_permissions, export_jobs, etc.) ---
    # create_all() handles this, but log for visibility
    existing_tables = set(inspector.get_table_names(schema=schema))
    expected_tables = {t.name for t in Base.metadata.tables.values()}
    missing = expected_tables - existing_tables
    if missing:
        logger.info(f"Tables to be created by create_all(): {missing}")


def init_db():
    """Create all tables in the database.

    For Lakebase deployments, ensures the schema is set correctly before
    creating tables. The schema is read from LAKEBASE_SCHEMA env var.

    Also runs lightweight migrations to add columns that were introduced
    after the initial table creation (create_all only creates new tables,
    it does not alter existing ones).
    """
    # Import all models to ensure they're registered with Base.metadata
    # This is necessary for create_all() to create all tables
    import src.database.models  # noqa: F401

    engine = get_engine()
    schema = os.getenv("LAKEBASE_SCHEMA")
    
    if schema:
        # For Lakebase: set schema on all tables that don't have one
        # This ensures CREATE TABLE uses the correct schema
        logger.info(f"Setting schema '{schema}' for table creation")
        
        # Execute SET search_path before creating tables
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text(f'SET search_path TO "{schema}"'))
            conn.commit()
        
        # Also set schema on metadata for table creation
        for table in Base.metadata.tables.values():
            if table.schema is None:
                table.schema = schema
    
    # Run migrations BEFORE create_all so existing tables get new columns
    _run_migrations(engine)

    # Create any entirely new tables
    Base.metadata.create_all(bind=engine)
