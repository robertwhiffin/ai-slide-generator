"""FastAPI application for AI Slide Generator.

This module initializes the FastAPI app with CORS middleware and routes.
In production, also serves the React frontend as static files.
"""

import asyncio
import logging
import os
from contextlib import AsyncExitStack, ExitStack, asynccontextmanager
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import admin, agent_config, chat, export, feedback, images, profiles, sessions, slides, tools, tour, verification, version, google_slides, setup, local_version
from src.api.routes.deck_contributors import router as deck_contributors_router
from src.core.databricks_client import get_or_create_user_client, set_user_client
from src.core.user_context import get_current_user as get_ctx_user, set_current_user
from src.core.permission_context import (
    build_permission_context,
    set_permission_context,
)
from src.api.routes.settings import (
    contributors_router,
    deck_prompts_router,
    identities_router,
    slide_styles_router,
)
from src.api.services.export_job_queue import start_export_worker
from src.api.services.job_queue import recover_stuck_requests, start_worker
from src.core.database import (
    get_session_local,
    init_db,
    is_lakebase_environment,
    start_token_refresh,
    stop_token_refresh,
)
from src.core.migrate_profiles_to_agent_config import migrate_profiles, backfill_sessions

logger = logging.getLogger(__name__)

# Detect environment
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT == "production"
IS_TESTING = ENVIRONMENT == "test"

# Worker task references for cleanup
_worker_task = None
_export_worker_task = None
_cleanup_task = None
_timeout_task = None
_frontend_assets_stack: ExitStack | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events."""
    global _worker_task, _export_worker_task, _cleanup_task, _timeout_task, _frontend_assets_stack

    # Startup
    logger.info(f"Starting AI Slide Generator API (environment: {ENVIRONMENT})")

    # The FastMCP streamable-HTTP transport spawns per-session async tasks
    # inside a task group owned by its StreamableHTTPSessionManager. That
    # task group is initialised by ``session_manager.run()`` and is
    # required before ``handle_request`` will accept any POST. When the
    # MCP app is nested under FastAPI via ``app.mount("/mcp", ...)``,
    # Starlette does NOT run the nested app's lifespan, so we have to
    # enter the session manager context here. AsyncExitStack guarantees
    # clean teardown of the task group on shutdown alongside the other
    # worker tasks below.
    #
    # Skipped under pytest: ``StreamableHTTPSessionManager.run()`` can
    # only be entered once per process, and unit-test suites instantiate
    # the ``TestClient`` (and therefore the lifespan) multiple times
    # against the same module-level FastMCP singleton. MCP endpoint
    # coverage lives in the integration tests, which set up their own
    # session manager lifecycle.
    mcp_lifespan_stack = AsyncExitStack()
    if os.getenv("PYTEST_CURRENT_TEST") is None:
        from src.api.mcp_server import mcp as tellr_mcp

        await mcp_lifespan_stack.enter_async_context(
            tellr_mcp.session_manager.run()
        )
        logger.info("MCP session manager started")
    else:
        logger.info("Pytest detected: skipping MCP session manager startup")

    # Start Lakebase token refresh if running in Databricks Apps
    # Must happen before init_db() so OAuth token is ready for database connections
    if is_lakebase_environment():
        try:
            await start_token_refresh()
            logger.info("Lakebase token refresh started")
        except Exception as e:
            logger.error(f"Failed to start Lakebase token refresh: {e}")
            raise

    # Initialize database tables (idempotent - only creates tables that don't exist)
    is_pytest = os.getenv("PYTEST_CURRENT_TEST") is not None
    if not is_pytest:
        try:
            init_db()
            logger.info("Database tables initialized")

            migrated = migrate_profiles(get_session_local())
            if migrated:
                logger.info(f"Migrated {migrated} profiles to agent_config")
            backfilled = backfill_sessions(get_session_local())
            if backfilled:
                logger.info(f"Backfilled {backfilled} sessions with agent_config")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    else:
        logger.info("Pytest detected: skipping database initialization")

    if IS_PRODUCTION:
        logger.info("Production mode: serving frontend from package assets")
        frontend_result = _resolve_frontend_dist()
        if frontend_result:
            _frontend_assets_stack, frontend_dist = frontend_result
            _mount_frontend(app, frontend_dist)
        else:
            logger.warning("Frontend assets not found in package")

    # Skip background workers and recovery in test mode
    if not IS_TESTING:
        # Start the job queue worker for async chat processing
        _worker_task = await start_worker()
        logger.info("Chat job queue worker started")

        # Start the export worker for async PPTX export processing
        _export_worker_task = await start_export_worker()
        logger.info("Export job queue worker started")

        # Start the MCP job timeout sweeper
        from src.api.services.job_queue import mark_timed_out_jobs_loop
        _timeout_task = asyncio.create_task(mark_timed_out_jobs_loop())
        logger.info("MCP job timeout sweeper started")

        # Start the request log cleanup task
        from src.api.middleware.request_logging import request_log_cleanup_loop
        _cleanup_task = asyncio.create_task(request_log_cleanup_loop())
        logger.info("Request log cleanup task started")

        # Recover any stuck requests from previous crashes
        try:
            recovered = await recover_stuck_requests()
            if recovered > 0:
                logger.info(f"Recovered {recovered} stuck chat requests")
        except Exception as e:
            logger.warning(f"Failed to recover stuck requests: {e}")
    else:
        logger.info("Test mode: skipping background workers and recovery")

    yield

    # Shutdown
    logger.info("Shutting down AI Slide Generator API")

    # Stop Lakebase token refresh
    await stop_token_refresh()

    # Cancel the worker tasks
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        logger.info("Chat job queue worker stopped")

    if _export_worker_task:
        _export_worker_task.cancel()
        try:
            await _export_worker_task
        except asyncio.CancelledError:
            pass
        logger.info("Export job queue worker stopped")

    if _cleanup_task:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("Request log cleanup task stopped")

    if _timeout_task:
        _timeout_task.cancel()
        try:
            await _timeout_task
        except asyncio.CancelledError:
            pass
        logger.info("MCP job timeout sweeper stopped")

    # Tear down the FastMCP session manager's task group. Safe to call
    # unconditionally — the stack was entered unconditionally at startup.
    await mcp_lifespan_stack.aclose()
    logger.info("MCP session manager stopped")

    if _frontend_assets_stack:
        _frontend_assets_stack.close()
        _frontend_assets_stack = None


# Initialize FastAPI app
app = FastAPI(
    title="AI Slide Generator API",
    description="Generate presentation slides from natural language using AI",
    version="0.3.0 (Phase 3 - Databricks Apps)",
    lifespan=lifespan,
)


@app.middleware("http")
async def normalize_mcp_path(request: Request, call_next):
    """Make POST /mcp behave like POST /mcp/.

    The SPA catch-all (``@app.get("/{full_path:path}")`` added by
    ``_mount_frontend``) intercepts non-GET requests to ``/mcp`` and
    causes Starlette to return 405 instead of routing to the FastMCP
    Mount. Rewriting the ASGI scope path before route resolution
    sidesteps that interaction and avoids emitting a 307 the client
    has to follow (which can drop ``Authorization`` or method-downgrade
    in misbehaving HTTP clients — Claude Code v2.1.123 via stdio→HTTP
    proxy was the original report).

    GET is left alone so ``/mcp`` continues to render the SPA in a
    browser. The match is exact so ``/mcp/``, ``/mcp/anything``, and
    ``/mcp-something`` are all unaffected; query strings live in
    ``scope["query_string"]`` and are not touched.
    """
    if request.url.path == "/mcp" and request.method != "GET":
        request.scope["path"] = "/mcp/"
        request.scope["raw_path"] = b"/mcp/"
    return await call_next(request)


def _resolve_frontend_dist() -> tuple[ExitStack, Path] | None:
    """Resolve frontend assets bundled in the app package."""
    try:
        assets_root = resources.files("databricks_tellr_app") / "_assets" / "frontend"
    except ModuleNotFoundError:
        return None

    if not assets_root.is_dir():
        return None

    stack = ExitStack()
    resolved_path = stack.enter_context(resources.as_file(assets_root))
    return stack, Path(resolved_path)


def _mount_frontend(app: FastAPI, frontend_dist: Path) -> None:
    """Mount static assets and SPA routes from the packaged frontend."""
    logger.info(f"Serving frontend from: {frontend_dist}")

    app.mount(
        "/assets",
        StaticFiles(directory=str(frontend_dist / "assets")),
        name="assets",
    )

    @app.get("/favicon.svg")
    async def serve_favicon():
        """Serve favicon."""
        favicon_path = frontend_dist / "favicon.svg"
        if favicon_path.exists():
            return FileResponse(str(favicon_path), media_type="image/svg+xml")
        raise HTTPException(status_code=404, detail="Favicon not found")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve React SPA for all non-API routes."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")

        index_path = frontend_dist / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=500, detail="Frontend not bundled in package")

        return FileResponse(str(index_path))


# Configure CORS only for development
if not IS_PRODUCTION:
    logger.info("Development mode: enabling CORS")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",  # React dev server
            "http://localhost:5173",  # Vite default port
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# User authentication middleware for on-behalf-of-user authorization
@app.middleware("http")
async def user_auth_middleware(request: Request, call_next):
    """
    Extract user token from Databricks Apps proxy and create user-scoped client.

    When running as a Databricks App, the proxy forwards the authenticated user's
    token in the x-forwarded-access-token header. This middleware extracts that
    token and creates a request-scoped WorkspaceClient for Genie/LLM/MLflow calls.

    It also populates:
    - Request-scoped user identity (``set_current_user``) for username access
    - Permission context (``set_permission_context``) with user ID and group IDs
      for permission checks on profiles/sessions

    In local development (no token header), the identity falls back to the
    ``DEV_USER_ID`` environment variable.
    """
    token = request.headers.get("x-forwarded-access-token")
    client_id = os.getenv("DATABRICKS_CLIENT_ID", "")

    user_id = None
    user_name = None

    if token:
        # Diagnostic logging: check if token is service principal ID (debug to avoid log spam on every request/poll)
        token_prefix = token[:20] if len(token) > 20 else token
        is_sp_token = client_id and token.startswith(client_id)
        logger.debug(
            "OBO auth: extracted token from header",
            extra={
                "token_prefix": token_prefix,
                "token_length": len(token),
                "is_service_principal": is_sp_token,
                "header_present": True,
            },
        )
        if is_sp_token:
            logger.warning("OBO auth: token appears to be service principal ID, not user token!")
        try:
            user_client = get_or_create_user_client(token)
            set_user_client(user_client)
            logger.debug("OBO auth: user client set successfully")
            # Extract user info from the token-scoped client
            try:
                me = user_client.current_user.me()
                user_id = me.id
                user_name = me.user_name
                set_current_user(user_name)
            except Exception as e:
                logger.warning(f"OBO auth: failed to resolve user info from token: {e}")
        except Exception as e:
            logger.warning(f"Failed to create user client from token: {e}")
    else:
        # Local / dev fallback: use DEV_USER_ID env var
        dev_user = os.getenv("DEV_USER_ID", "dev@local.dev")
        user_name = dev_user
        user_id = os.getenv("DEV_USER_DATABRICKS_ID")  # Optional: set for testing
        set_current_user(dev_user)
        logger.debug("OBO auth: no token header — using dev identity %s", dev_user)

    # Build and set permission context
    # Group fetching disabled — deck sharing uses user identities only, not groups
    permission_ctx = build_permission_context(
        user_id=user_id,
        user_name=user_name,
        fetch_groups=False,
    )
    set_permission_context(permission_ctx)

    # Record user login for local identity table (non-blocking)
    if user_id and user_name and IS_PRODUCTION:
        try:
            from src.services.identity_provider import get_identity_provider
            provider = get_identity_provider()
            provider.record_user_login(
                user_id=user_id,
                user_name=user_name,
                display_name=user_name,  # Could get from me.display_name if available
            )
        except Exception as e:
            logger.debug(f"Failed to record user login: {e}")

    try:
        response = await call_next(request)
        return response
    finally:
        # Always clean up request-scoped state
        set_user_client(None)
        set_current_user(None)
        set_permission_context(None)


# Request logging middleware - registered after auth middleware so it wraps outermost
from src.api.middleware.request_logging import RequestLoggingMiddleware

app.add_middleware(RequestLoggingMiddleware)

# Include API routers
app.include_router(admin.router)
app.include_router(agent_config.router)
app.include_router(chat.router)
app.include_router(feedback.router)
app.include_router(images.router)
app.include_router(slides.router)
app.include_router(tools.router)
app.include_router(export.router)
app.include_router(sessions.router)
app.include_router(verification.router)
app.include_router(version.router)
app.include_router(google_slides.router)
app.include_router(setup.router)
app.include_router(local_version.router)
app.include_router(tour.router)
app.include_router(profiles.router)
app.include_router(profiles.load_router)
app.include_router(deck_contributors_router)

# Configuration management routers (slide_styles and deck_prompts are global libraries, still needed)
app.include_router(contributors_router, prefix="/api/settings", tags=["settings"])
app.include_router(deck_prompts_router, prefix="/api/settings", tags=["settings"])
app.include_router(identities_router, prefix="/api/settings", tags=["settings"])
app.include_router(slide_styles_router, prefix="/api/settings", tags=["settings"])

# MCP server — mount the FastMCP streamable-HTTP ASGI app at /mcp.
# Must be registered before the SPA catch-all (which is added lazily by
# ``_mount_frontend`` inside the lifespan when running in production),
# otherwise JSON-RPC POSTs to /mcp would be swallowed by the SPA route
# and return index.html instead of reaching the tool handlers.
#
# Set ``streamable_http_path = "/"`` so the sub-app's internal route is
# ``/``; when Starlette mounts the sub-app at ``/mcp`` it strips the
# ``/mcp`` prefix before forwarding, so an external POST to ``/mcp``
# lands on the sub-app's ``/`` route. Without this, the sub-app's
# default internal route would be ``/mcp`` and external requests would
# need to hit ``/mcp/mcp``.
from src.api.mcp_server import mcp as tellr_mcp  # noqa: E402
tellr_mcp.settings.streamable_http_path = "/"
app.mount("/mcp", tellr_mcp.streamable_http_app())
logger.info("MCP server mounted at /mcp")


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "environment": ENVIRONMENT,
        "version": "0.3.0",
    }


@app.get("/api/user/current")
async def get_current_user():
    """Return the current user's identity and permission context.

    The middleware already resolved the username (from the Databricks token in
    production, or ``DEV_USER_ID`` in local dev) and stored it via
    ``set_current_user``.  This endpoint simply reads that value, avoiding an
    extra Databricks API call.
    
    Also includes the user's Databricks ID and group IDs from the permission
    context, which are used for profile permission checks.
    """
    from src.core.permission_context import get_permission_context
    
    ctx_user = get_ctx_user()
    perm_ctx = get_permission_context()
    
    if ctx_user:
        result = {
            "username": ctx_user,
            "display_name": ctx_user,
        }
        # Include permission context info if available
        if perm_ctx:
            result["user_id"] = perm_ctx.user_id
            result["group_count"] = len(perm_ctx.group_ids)
        return result

    # Fallback: resolve from Databricks client (production without middleware hit)
    try:
        from src.core.databricks_client import get_user_client

        client = get_user_client()
        user = client.current_user.me()
        return {
            "username": user.user_name,
            "display_name": user.display_name or user.user_name,
            "user_id": user.id,
        }
    except Exception as e:
        logger.warning(f"Failed to get current user: {e}")
        return {
            "username": "user",
            "display_name": "User",
        }


# Development: API info at root
if not IS_PRODUCTION:

    @app.get("/")
    async def root():
        """Root endpoint with API information (development only)."""
        return {
            "name": "AI Slide Generator API",
            "version": "0.3.0",
            "environment": "development",
            "status": "operational",
            "message": "Frontend should be running on http://localhost:3000",
        }
