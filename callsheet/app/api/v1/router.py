"""v1 API surface. Every new route module is registered here and nowhere else."""

from fastapi import APIRouter

from app.api.v1.routes import (
    collection,
    health,
    invitations,
    me,
    organizations,
    title_memberships,
    title_previews,
    titles,
)

api_v1_router = APIRouter()
api_v1_router.include_router(health.router)
api_v1_router.include_router(me.router)
api_v1_router.include_router(organizations.router)
api_v1_router.include_router(invitations.router)
api_v1_router.include_router(titles.router)
api_v1_router.include_router(title_memberships.router)
api_v1_router.include_router(title_previews.router)
api_v1_router.include_router(collection.router)
