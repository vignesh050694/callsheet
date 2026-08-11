"""Application factory and process-wide wiring."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_v1_router
from app.core.config import Settings, get_settings
from app.core.exceptions import (
    AuthenticationRequiredError,
    DomainError,
    PermissionDeniedError,
    ResourceConflictError,
    ResourceNotFoundError,
    ValidationFailedError,
)
from app.core.logging_config import configure_logging
from app.db.session import engine
from app.middleware.request_logging import RequestLoggingMiddleware
from app.schemas.common import ErrorResponse

APP_VERSION = "0.1.0"
UNEXPECTED_ERROR_MESSAGE = "An unexpected error occurred"

DOMAIN_ERROR_STATUS_CODES: dict[type[DomainError], int] = {
    ResourceNotFoundError: 404,
    ResourceConflictError: 409,
    ValidationFailedError: 422,
    AuthenticationRequiredError: 401,
    PermissionDeniedError: 403,
}
DEFAULT_DOMAIN_ERROR_STATUS_CODE = 400

_logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown. Connection pools are disposed so reloads don't leak sockets."""
    settings = get_settings()
    _logger.info("app.startup", environment=settings.environment, version=APP_VERSION)
    yield
    await engine.dispose()
    _logger.info("app.shutdown")


def _register_middleware(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )


def _register_exception_handlers(app: FastAPI) -> None:
    """One place translating domain errors to HTTP, so services stay transport-agnostic."""

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, error: DomainError) -> JSONResponse:
        status_code = DOMAIN_ERROR_STATUS_CODES.get(type(error), DEFAULT_DOMAIN_ERROR_STATUS_CODE)
        _logger.warning("domain.error", code=error.code, status_code=status_code)
        body = ErrorResponse(
            code=error.code,
            message=error.message,
            request_id=getattr(request.state, "request_id", None),
        )
        return JSONResponse(status_code=status_code, content=body.model_dump())

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        _logger.error("unhandled.error", error=str(error), exc_info=True)
        body = ErrorResponse(
            code="InternalServerError",
            message=UNEXPECTED_ERROR_MESSAGE,
            request_id=getattr(request.state, "request_id", None),
        )
        return JSONResponse(status_code=500, content=body.model_dump())


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="Callsheet API",
        description="Backend for the Agentic Social Media Control Centre.",
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    _register_middleware(app, settings)
    _register_exception_handlers(app)
    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
