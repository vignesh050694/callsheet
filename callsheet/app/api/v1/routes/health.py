"""Liveness endpoint. Deliberately does not touch the database."""

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.common import HealthResponse

APP_VERSION = "0.1.0"

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def read_health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        version=APP_VERSION,
    )
