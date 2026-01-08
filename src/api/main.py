"""FastAPI application for AI Slide Generator.

This module initializes the FastAPI app with CORS middleware and routes.
In production, also serves the React frontend as static files.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import chat, slides, export, sessions, verification
from src.core.databricks_client import create_user_client, set_user_client
from src.api.routes.settings import (
    ai_infra_router,
    deck_prompts_router,
    genie_router,
    mlflow_router,
    profiles_router,
    prompts_router,
    slide_styles_router,
)
from src.api.services.job_queue import recover_stuck_requests, start_worker

logger = logging.getLogger(__name__)

# Detect environment
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT == "production"

# Worker task reference for cleanup
_worker_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events."""
    global _worker_task

    # Startup
    logger.info(f"Starting AI Slide Generator API (environment: {ENVIRONMENT})")
    if IS_PRODUCTION:
        logger.info("Production mode: serving frontend from static files")

    # Start the job queue worker for async chat processing
    _worker_task = await start_worker()
    logger.info("Job queue worker started")

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

    # Cancel the worker task
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        logger.info("Job queue worker stopped")


# Initialize FastAPI app
app = FastAPI(
    title="AI Slide Generator API",
    description="Generate presentation slides from natural language using AI",
    version="0.3.0 (Phase 3 - Databricks Apps)",
    lifespan=lifespan,
)

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
    if token:
        try:
            user_client = create_user_client(token)
            set_user_client(user_client)
            logger.debug("User client set from forwarded token")
        except Exception as e:
            logger.warning(f"Failed to create user client from token: {e}")
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

# Configuration management routers
app.include_router(profiles_router, prefix="/api/settings", tags=["settings"])
app.include_router(ai_infra_router, prefix="/api/settings", tags=["settings"])
app.include_router(deck_prompts_router, prefix="/api/settings", tags=["settings"])
app.include_router(genie_router, prefix="/api/settings", tags=["settings"])
app.include_router(mlflow_router, prefix="/api/settings", tags=["settings"])
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


# Production: Serve frontend static files
if IS_PRODUCTION:
    # Get path to frontend dist directory
    # In Databricks Apps, the source code path is the working directory
    # Try workspace location first, then fall back to relative path
    frontend_dist = Path.cwd() / "frontend" / "dist"
    if not frontend_dist.exists():
        # Fallback to relative path (for local testing)
        frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"

    if frontend_dist.exists():
        logger.info(f"Serving frontend from: {frontend_dist}")

        # Mount static assets (JS, CSS, images)
        app.mount(
            "/assets",
            StaticFiles(directory=str(frontend_dist / "assets")),
            name="assets",
        )

        # Serve favicon from dist root
        @app.get("/favicon.svg")
        async def serve_favicon():
            """Serve favicon."""
            favicon_path = frontend_dist / "favicon.svg"
            if favicon_path.exists():
                return FileResponse(str(favicon_path), media_type="image/svg+xml")
            raise HTTPException(status_code=404, detail="Favicon not found")

        # Serve index.html for all other routes (SPA routing)
        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            """Serve React SPA for all non-API routes."""
            # API routes are already handled by routers
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")

            # Serve index.html for all other routes
            index_path = frontend_dist / "index.html"
            if not index_path.exists():
                raise HTTPException(
                    status_code=500, detail="Frontend not built. Run: npm run build"
                )

            return FileResponse(str(index_path))

    else:
        logger.warning(
            f"Frontend dist directory not found: {frontend_dist}. "
            "Frontend will not be served. Run 'npm run build' in frontend directory."
        )


# Development: API info at root
else:

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

