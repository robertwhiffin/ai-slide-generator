"""FastAPI application for AI Slide Generator.

This module initializes the FastAPI app with CORS middleware and routes.
In production, also serves the React frontend as static files.
"""

import asyncio
import logging
import os
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from importlib import resources

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import chat, slides, export, sessions, verification, version
from src.core.databricks_client import create_user_client, set_user_client
from src.core.database import (
    is_lakebase_environment,
    start_token_refresh,
    stop_token_refresh,
)
from src.api.routes.settings import (
    ai_infra_router,
    deck_prompts_router,
    genie_router,
    profiles_router,
    prompts_router,
    slide_styles_router,
)
from src.api.services.job_queue import recover_stuck_requests, start_worker
from src.api.services.export_job_queue import start_export_worker

logger = logging.getLogger(__name__)

# Detect environment
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT == "production"

# Worker task references for cleanup
_worker_task = None
_export_worker_task = None
_frontend_assets_stack: ExitStack | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events."""
    global _worker_task, _export_worker_task, _frontend_assets_stack

    # Startup
    logger.info(f"Starting AI Slide Generator API (environment: {ENVIRONMENT})")

    # Start Lakebase token refresh if running in Databricks Apps
    if is_lakebase_environment():
        try:
            await start_token_refresh()
            logger.info("Lakebase token refresh started")
        except Exception as e:
            logger.error(f"Failed to start Lakebase token refresh: {e}")
            raise

    if IS_PRODUCTION:
        logger.info("Production mode: serving frontend from package assets")
        frontend_result = _resolve_frontend_dist()
        if frontend_result:
            _frontend_assets_stack, frontend_dist = frontend_result
            _mount_frontend(app, frontend_dist)
        else:
            logger.warning("Frontend assets not found in package")

    # Start the job queue worker for async chat processing
    _worker_task = await start_worker()
    logger.info("Chat job queue worker started")

    # Start the export worker for async PPTX export processing
    _export_worker_task = await start_export_worker()
    logger.info("Export job queue worker started")

    # Recover any stuck requests from previous crashes
    try:
        recovered = await recover_stuck_requests()
        if recovered > 0:
            logger.info(f"Recovered {recovered} stuck chat requests")
    except Exception as e:
        logger.warning(f"Failed to recover stuck requests: {e}")

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
            raise HTTPException(
                status_code=500, detail="Frontend not bundled in package"
            )

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

    In local development (no token header), operations fall back to system client.
    """
    token = request.headers.get("x-forwarded-access-token")
    client_id = os.getenv("DATABRICKS_CLIENT_ID", "")

    if token:
        # Diagnostic logging: check if token is service principal ID
        token_prefix = token[:20] if len(token) > 20 else token
        is_sp_token = client_id and token.startswith(client_id)
        logger.warning(
            "OBO auth: extracted token from header",
            extra={
                "token_prefix": token_prefix,
                "token_length": len(token),
                "is_service_principal": is_sp_token,
                "header_present": True,
            },
        )
        if is_sp_token:
            logger.warning(
                "OBO auth: token appears to be service principal ID, not user token!"
            )
        try:
            user_client = create_user_client(token)
            set_user_client(user_client)
            logger.warning("OBO auth: user client set successfully")
        except Exception as e:
            logger.warning(f"Failed to create user client from token: {e}")
    else:
        logger.warning("OBO auth: no x-forwarded-access-token header present")
    try:
        response = await call_next(request)
        return response
    finally:
        # Always clean up the user client after request
        set_user_client(None)


# Include API routers
app.include_router(chat.router)
app.include_router(slides.router)
app.include_router(export.router)
app.include_router(sessions.router)
app.include_router(verification.router)
app.include_router(version.router)

# Configuration management routers
app.include_router(profiles_router, prefix="/api/settings", tags=["settings"])
app.include_router(ai_infra_router, prefix="/api/settings", tags=["settings"])
app.include_router(deck_prompts_router, prefix="/api/settings", tags=["settings"])
app.include_router(genie_router, prefix="/api/settings", tags=["settings"])
app.include_router(prompts_router, prefix="/api/settings", tags=["settings"])
app.include_router(slide_styles_router, prefix="/api/settings", tags=["settings"])


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
    """Get the current user from Databricks workspace client.

    Uses user-scoped client when running as Databricks App (user's identity),
    falls back to system client in local development (service principal).
    """
    try:
        from src.core.databricks_client import get_user_client
        client = get_user_client()
        user = client.current_user.me()
        return {
            "username": user.user_name,
            "display_name": user.display_name or user.user_name,
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

