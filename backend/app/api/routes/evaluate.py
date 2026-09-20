"""Standalone evaluation endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, provider_registry
from app.evaluation.base import CRITERIA
from app.evaluation.factory import available_modes
from app.providers.registry import ProviderRegistry
from app.schemas.evaluation import EvaluateRequest, EvaluateResponse
from app.services import evaluation_service

router = APIRouter(tags=["evaluation"])


@router.post("/evaluate", response_model=EvaluateResponse, summary="Score stored results")
async def evaluate(
    payload: EvaluateRequest,
    session: AsyncSession = Depends(db_session),
    registry: ProviderRegistry = Depends(provider_registry),
) -> EvaluateResponse:
    """Scores one result (``model_result_id``) or every result in a run (``run_id``).

    Per-result failures are reported in ``errors`` rather than failing the request,
    so one unparseable judge response never discards the rest of the scores.
    """
    return await evaluation_service.evaluate(session, payload, registry)


@router.get("/evaluation/modes", summary="Available evaluation modes")
async def evaluation_modes() -> dict[str, Any]:
    return {"modes": available_modes(), "criteria": list(CRITERIA)}
