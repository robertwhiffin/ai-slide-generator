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


def _get_lakebase_type() -> str:
    """Get the Lakebase type: 'autoscaling', 'provisioned', or '' (not Lakebase)."""
    return os.getenv("LAKEBASE_TYPE", "")


def is_lakebase_environment() -> bool:
    """Check if running in a Lakebase environment (Databricks Apps).

    Returns:
        True if LAKEBASE_TYPE is set, or PGHOST and PGUSER are set (provisioned auto-inject)
    """
    if os.getenv("LAKEBASE_TYPE"):
        return True
    return bool(os.getenv("PGHOST") and os.getenv("PGUSER"))


def _generate_lakebase_token() -> str:
    """Generate a fresh OAuth token for Lakebase authentication.

    Uses the appropriate API based on LAKEBASE_TYPE:
    - autoscaling: ws.postgres.generate_database_credential(endpoint=...)
    - provisioned: ws.database.generate_database_credential(instance_names=[...])

    Returns:
        OAuth token string to use as PostgreSQL password

    Raises:
        RuntimeError: If required env vars not set or token generation fails
    """
    from src.core.databricks_client import get_system_client

    ws = get_system_client()
    lakebase_type = _get_lakebase_type()

    if lakebase_type == "autoscaling":
        # Autoscaling Lakebase uses ws.postgres API
        endpoint_name = os.getenv("LAKEBASE_ENDPOINT_NAME")
        if not endpoint_name:
            raise RuntimeError(
                "LAKEBASE_ENDPOINT_NAME not set — cannot generate autoscaling Lakebase token."
            )
        cred = ws.postgres.generate_database_credential(endpoint=endpoint_name)
        logger.info("Generated Lakebase OAuth token via ws.postgres (autoscaling)")
        return cred.token
    else:
        # Provisioned Lakebase uses ws.database API
        instance_name = os.getenv("LAKEBASE_INSTANCE")
        if not instance_name:
            raise RuntimeError(
                "LAKEBASE_INSTANCE not set — cannot generate Lakebase token."
            )
        cred = ws.database.generate_database_credential(
            request_id=str(uuid.uuid4()),
            instance_names=[instance_name],
        )
        logger.info("Generated Lakebase OAuth token via ws.database (provisioned)")
        return cred.token


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
    _postgres_token = _generate_lakebase_token()
    _last_token_refresh = time.time()
    logger.info("Generated initial Lakebase OAuth token")
    return _postgres_token


async def _refresh_token_background() -> None:
    """Background task to refresh Lakebase OAuth tokens periodically.

    Tokens expire after 1 hour, so we refresh at ~50 minutes with jitter
    (+-5 min) to avoid synchronized refresh spikes across replicas.
    """
    import random

    global _postgres_token, _last_token_refresh

    while True:
        try:
            # Add jitter: 45-55 minutes
            jitter = random.uniform(-5 * 60, 5 * 60)
            sleep_time = TOKEN_REFRESH_INTERVAL_SECONDS + jitter
            await asyncio.sleep(sleep_time)

            # Check remaining TTL — refresh early if under 10 min
            elapsed = time.time() - _last_token_refresh
            if elapsed < (TOKEN_REFRESH_INTERVAL_SECONDS - 10 * 60):
                continue  # Token still fresh enough

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
    _postgres_token = _generate_lakebase_token()
    _last_token_refresh = time.time()
    logger.info("Initial Lakebase OAuth token generated")

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

    # Check for autoscaling Lakebase (env vars set by deployment)
    lakebase_type = _get_lakebase_type()
    if lakebase_type == "autoscaling":
        pg_host = os.getenv("LAKEBASE_PG_HOST")
        if not pg_host:
            raise RuntimeError(
                "LAKEBASE_PG_HOST required when LAKEBASE_TYPE=autoscaling"
            )
        # Use PGUSER if set (from AppResourceDatabase), otherwise resolve from SDK
        pg_user = os.getenv("PGUSER")
        if not pg_user:
            from src.core.databricks_client import get_system_client
            ws = get_system_client()
            pg_user = ws.current_user.me().user_name

        database = "databricks_postgres"
        schema = os.getenv("LAKEBASE_SCHEMA", "app_data")
        logger.info(f"Detected autoscaling Lakebase environment (host: {pg_host}, user: {pg_user})")

        url = f"postgresql://{pg_user}@{pg_host}:5432/{database}?sslmode=require"
        if schema:
            url += f"&options=-csearch_path%3D{schema}"
        return url

    # Check for provisioned Lakebase (PGHOST auto-set by Databricks Apps)
    pg_host = os.getenv("PGHOST")
    pg_user = os.getenv("PGUSER")

    if pg_host and pg_user:
        # Running on Databricks Apps with provisioned Lakebase
        logger.info(f"Detected provisioned Lakebase environment (PGHOST: {pg_host})")

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


def init_db():
    """Create all tables in the database.

    For Lakebase deployments, ensures the schema is set correctly before
    creating tables. The schema is read from LAKEBASE_SCHEMA env var.
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
    
    Base.metadata.create_all(bind=engine)

    # Run migrations for columns that create_all() won't add to existing tables
    _run_migrations(engine, schema)


def _run_migrations(engine, schema: str | None = None):
    """Add columns and run data migrations that create_all() won't handle.

    SQLAlchemy's create_all() only creates new tables; it does not alter
    existing ones. This function:
    - Adds missing columns via ALTER TABLE
    - Migrates google_credentials_encrypted from config_profiles to google_global_credentials
    - Removes profile_id from google_oauth_tokens (SQLite: recreate table)
    All steps are idempotent.
    """
    from sqlalchemy import inspect, text

    is_sqlite = engine.dialect.name == "sqlite"
    _qual = lambda t: f'"{schema}"."{t}"' if schema else f'"{t}"'

    # --- config_profiles: add is_deleted, deleted_at ---
    table_name = "config_profiles"
    qualified_table = _qual(table_name)

    with engine.begin() as conn:
        inspector = inspect(conn)
        try:
            columns = {c["name"] for c in inspector.get_columns(table_name, schema=schema)}
        except Exception:
            return
        if "is_deleted" not in columns:
            logger.info(f"Migration: adding is_deleted column to {table_name}")
            conn.execute(text(
                f"ALTER TABLE {qualified_table} ADD COLUMN is_deleted BOOLEAN DEFAULT FALSE NOT NULL"
            ))
        if "deleted_at" not in columns:
            logger.info(f"Migration: adding deleted_at column to {table_name}")
            conn.execute(text(
                f"ALTER TABLE {qualified_table} ADD COLUMN deleted_at TIMESTAMP NULL"
            ))

        # --- Migrate google_credentials_encrypted to google_global_credentials ---
        _migrate_google_credentials_to_global(conn, inspector, schema, _qual, is_sqlite)

        # --- Remove profile_id from google_oauth_tokens ---
        _migrate_drop_profile_id_from_oauth_tokens(conn, inspector, schema, _qual, is_sqlite)


def _migrate_google_credentials_to_global(conn, inspector, schema, _qual, is_sqlite):
    """Copy first non-null google_credentials_encrypted to global table, then null out profiles."""
    from sqlalchemy import text

    profiles_table = "config_profiles"
    global_table = "google_global_credentials"

    try:
        profiles_cols = {c["name"] for c in inspector.get_columns(profiles_table, schema=schema)}
    except Exception:
        return

    if "google_credentials_encrypted" not in profiles_cols:
        return

    try:
        global_cols = {c["name"] for c in inspector.get_columns(global_table, schema=schema)}
    except Exception:
        return

    if "credentials_encrypted" not in global_cols:
        return

    q_profiles = _qual(profiles_table)
    q_global = _qual(global_table)

    # Idempotent: only run if global table is empty and profiles have data
    result = conn.execute(text(f"SELECT COUNT(*) FROM {q_global}")).scalar()
    if result and result > 0:
        return

    row = conn.execute(text(
        f"SELECT google_credentials_encrypted FROM {q_profiles} "
        "WHERE google_credentials_encrypted IS NOT NULL LIMIT 1"
    )).fetchone()

    if not row or row[0] is None:
        return

    logger.info("Migration: copying google_credentials_encrypted to google_global_credentials")
    conn.execute(
        text(
            f"INSERT INTO {q_global} (credentials_encrypted, uploaded_by, created_at, updated_at) "
            "VALUES (:creds, 'migration', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"creds": row[0]},
    )
    conn.execute(text(f"UPDATE {q_profiles} SET google_credentials_encrypted = NULL"))


def _migrate_drop_profile_id_from_oauth_tokens(conn, inspector, schema, _qual, is_sqlite):
    """Remove profile_id column from google_oauth_tokens. SQLite: recreate table."""
    from sqlalchemy import text

    table_name = "google_oauth_tokens"

    try:
        columns = {c["name"] for c in inspector.get_columns(table_name, schema=schema)}
    except Exception:
        return

    if "profile_id" not in columns:
        return

    q_table = _qual(table_name)

    if is_sqlite:
        tmp = f"{table_name}_new"
        q_tmp = _qual(tmp) if schema else tmp
        conn.execute(text(f"""
            CREATE TABLE {q_tmp} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_identity VARCHAR(255) NOT NULL,
                token_encrypted TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        conn.execute(text(
            f"INSERT INTO {q_tmp} (id, user_identity, token_encrypted, created_at, updated_at) "
            f"SELECT id, user_identity, token_encrypted, created_at, updated_at FROM {q_table}"
        ))
        conn.execute(text(f"DROP TABLE {q_table}"))
        conn.execute(text(f"ALTER TABLE {q_tmp} RENAME TO {table_name}"))
    else:
        conn.execute(text(f"ALTER TABLE {q_table} DROP COLUMN profile_id"))
