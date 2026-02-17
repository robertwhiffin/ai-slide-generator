"""Configuration API routes."""
from src.api.routes.settings.ai_infra import router as ai_infra_router
from src.api.routes.settings.deck_prompts import router as deck_prompts_router
from src.api.routes.settings.genie import router as genie_router
from src.api.routes.settings.profiles import router as profiles_router
from src.api.routes.settings.prompts import router as prompts_router
from src.api.routes.settings.slide_styles import router as slide_styles_router

__all__ = [
    "profiles_router",
    "ai_infra_router",
    "deck_prompts_router",
    "genie_router",
    "prompts_router",
    "slide_styles_router",
]

