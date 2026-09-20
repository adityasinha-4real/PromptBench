"""Provider and model endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import provider_registry
from app.providers.registry import ProviderRegistry
from app.schemas.model import ModelsResponse, TestConnectionRequest, TestConnectionResponse
from app.services import model_service

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=ModelsResponse, summary="List providers and their models")
async def list_models(
    probe: bool = Query(
        default=True,
        description="Check provider reachability. Set false for a configuration-only listing.",
    ),
    registry: ProviderRegistry = Depends(provider_registry),
) -> ModelsResponse:
    """Providers, their availability and every model that can be benchmarked.

    Never returns credentials — only whether the relevant environment variable
    is populated, and which variable that is.
    """
    return await model_service.list_models(registry, probe=probe)


@router.post(
    "/test",
    response_model=TestConnectionResponse,
    summary="Test a provider, optionally probing a specific model",
)
async def test_connection(
    payload: TestConnectionRequest,
    registry: ProviderRegistry = Depends(provider_registry),
) -> TestConnectionResponse:
    """Verifies credentials and reachability.

    Always returns 200 with ``available`` set — a failed check is a valid
    answer, not a server error.
    """
    return await model_service.test_connection(registry, payload.provider, payload.model)
