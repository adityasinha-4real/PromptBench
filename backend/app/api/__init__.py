"""HTTP API layer."""

from fastapi import APIRouter

from app.api.routes import analytics, benchmarks, evaluate, export, health, models, settings

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(models.router)
api_router.include_router(benchmarks.router)
api_router.include_router(evaluate.router)
api_router.include_router(analytics.router)
api_router.include_router(export.router)
api_router.include_router(settings.router)

__all__ = ["api_router"]
