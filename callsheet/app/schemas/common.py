"""Response shapes shared across every endpoint."""

from pydantic import BaseModel, Field

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class PageParams(BaseModel):
    """Query-string pagination, validated before it reaches the service."""

    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0)


class Page[ItemT](BaseModel):
    items: list[ItemT]
    total: int
    limit: int
    offset: int


class ErrorResponse(BaseModel):
    """Uniform error body, so the UI can branch on `code` rather than parse prose."""

    code: str
    message: str
    request_id: str | None = None


class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str
