"""API routes."""

from src.api.routes.chat import router as chat_router
from src.api.routes.slides import router as slides_router

__all__ = [
    "chat_router",
    "slides_router",
]
