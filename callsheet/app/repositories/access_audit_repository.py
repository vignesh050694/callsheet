"""Data access for the access audit log. Queries and appends only — never updates."""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access_audit import AccessAuditEvent

_logger = structlog.get_logger(__name__)


class AccessAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_title(self, title_id: uuid.UUID) -> list[AccessAuditEvent]:
        """Newest first — the question asked of an audit log is almost always "recently"."""
        _logger.debug("access_audit.query.list_for_title", title_id=str(title_id))
        result = await self._session.execute(
            select(AccessAuditEvent)
            .where(AccessAuditEvent.title_id == title_id)
            .order_by(AccessAuditEvent.created_at.desc(), AccessAuditEvent.id.desc())
        )
        return list(result.scalars().all())

    async def add(self, event: AccessAuditEvent) -> AccessAuditEvent:
        """Appends. There is deliberately no update or delete on this repository."""
        self._session.add(event)
        await self._session.flush()
        return event
