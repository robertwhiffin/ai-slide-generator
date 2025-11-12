"""FastAPI application for AI Slide Generator.

This module initializes the FastAPI app with CORS middleware and routes.
Phase 1: Single session, basic error handling.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import chat, slides

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events."""
    # Startup
    logger.info("Starting AI Slide Generator API")
    yield
    # Shutdown
    logger.info("Shutting down AI Slide Generator API")


# Initialize FastAPI app
app = FastAPI(
    title="AI Slide Generator API",
    description="Generate presentation slides from natural language using AI",
    version="0.2.0 (Phase 2 - Enhanced UI)",
    lifespan=lifespan,
)

# Configure CORS for local development
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

# Include routers
app.include_router(chat.router)
app.include_router(slides.router)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "AI Slide Generator API",
        "version": "0.2.0",
        "phase": "Phase 2 - Enhanced UI (Drag-and-Drop, Editing)",
        "status": "operational",
    }

