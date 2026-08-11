"""Model package. Import every model here so Alembic autogenerate sees the full metadata."""

from app.models.base import Base
from app.models.organization import Organization, OrganizationType

__all__ = ["Base", "Organization", "OrganizationType"]
