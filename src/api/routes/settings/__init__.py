"""Configuration API routes."""
from src.api.routes.settings.deck_prompts import router as deck_prompts_router
from src.api.routes.settings.slide_styles import router as slide_styles_router

__all__ = [
    "deck_prompts_router",
    "slide_styles_router",
]

