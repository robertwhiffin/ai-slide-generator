"""Configuration API routes."""
from src.api.routes.settings.contributors import router as contributors_router
from src.api.routes.settings.deck_prompts import router as deck_prompts_router
from src.api.routes.settings.design_systems import router as design_systems_router
from src.api.routes.settings.identities import router as identities_router
from src.api.routes.settings.slide_styles import router as slide_styles_router

__all__ = [
    "contributors_router",
    "deck_prompts_router",
    "design_systems_router",
    "identities_router",
    "slide_styles_router",
]
