"""Request logging middleware.

Applied once, globally, in `app.main`. Controllers never log request start/end
themselves. Every request gets a correlation id, and every response is logged with
its duration measured on a monotonic clock (wall-clock subtraction is unreliable
across await boundaries).
"""

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

REQUEST_ID_HEADER = "X-Request-ID"
SERVER_ERROR_STATUS_THRESHOLD = 500
CLIENT_ERROR_STATUS_THRESHOLD = 400

_logger = structlog.get_logger("app.request")

RequestHandler = Callable[[Request], Awaitable[Response]]


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs the start and end of every request, with timing and a correlation id."""

    def __init__(self, app: ASGIApp, *, excluded_paths: frozenset[str] | None = None) -> None:
        super().__init__(app)
        self._excluded_paths = excluded_paths or frozenset()

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id

        if request.url.path in self._excluded_paths:
            return await call_next(request)

        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        started_at = time.perf_counter()
        _logger.info("request.start", query=str(request.url.query) or None)

        try:
            response = await call_next(request)
        except Exception as error:
            duration_ms = self._elapsed_ms(started_at)
            _logger.error(
                "request.failed",
                duration_ms=duration_ms,
                error=str(error),
                exc_info=True,
            )
            structlog.contextvars.clear_contextvars()
            raise

        duration_ms = self._elapsed_ms(started_at)
        self._log_completed_request(response.status_code, duration_ms)
        response.headers[REQUEST_ID_HEADER] = request_id
        structlog.contextvars.clear_contextvars()
        return response

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        return round((time.perf_counter() - started_at) * 1000, 2)

    @staticmethod
    def _log_completed_request(status_code: int, duration_ms: float) -> None:
        """Level follows outcome: 5xx is an error, 4xx a warning, everything else info."""
        log_fields = {"status_code": status_code, "duration_ms": duration_ms}
        if status_code >= SERVER_ERROR_STATUS_THRESHOLD:
            _logger.error("request.end", **log_fields)
        elif status_code >= CLIENT_ERROR_STATUS_THRESHOLD:
            _logger.warning("request.end", **log_fields)
        else:
            _logger.info("request.end", **log_fields)
