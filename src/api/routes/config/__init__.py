"""Configuration API routes."""
from src.api.routes.config.ai_infra import router as ai_infra_router
from src.api.routes.config.genie import router as genie_router
from src.api.routes.config.mlflow import router as mlflow_router
from src.api.routes.config.profiles import router as profiles_router
from src.api.routes.config.prompts import router as prompts_router

__all__ = [
    "profiles_router",
    "ai_infra_router",
    "genie_router",
    "mlflow_router",
    "prompts_router",
]

