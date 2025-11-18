"""FastAPI application for AI Slide Generator.

This module initializes the FastAPI app with CORS middleware and routes.
In production, also serves the React frontend as static files.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import chat, slides

logger = logging.getLogger(__name__)

# Detect environment
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT == "production"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events."""
    # Startup
    logger.info(f"Starting AI Slide Generator API (environment: {ENVIRONMENT})")
    if IS_PRODUCTION:
        logger.info("Production mode: serving frontend from static files")
    yield
    # Shutdown
    logger.info("Shutting down AI Slide Generator API")


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

# Include API routers
app.include_router(chat.router)
app.include_router(slides.router)


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "environment": ENVIRONMENT,
        "version": "0.3.0",
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

