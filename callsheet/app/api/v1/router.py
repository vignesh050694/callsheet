"""v1 API surface. Every new route module is registered here and nowhere else."""

from fastapi import APIRouter

from app.api.v1.routes import health, invitations, me, organizations

api_v1_router = APIRouter()
api_v1_router.include_router(health.router)
api_v1_router.include_router(me.router)
api_v1_router.include_router(organizations.router)
api_v1_router.include_router(invitations.router)
