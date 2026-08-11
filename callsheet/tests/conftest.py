"""Test fixtures.

Tests run against in-memory SQLite so the suite needs no running Postgres. The
`get_db_session` dependency is overridden to hand every request the same session,
which keeps the whole test inside one transaction-free, disposable database.
"""

import os
from collections.abc import AsyncIterator

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LOG_LEVEL", "warning")
os.environ.setdefault("LOG_FORMAT", "console")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.session import get_db_session
from app.main import create_app
from app.models import Base, User

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
PILOT_USER_EMAIL = "head@sunpictures.com"
PILOT_USER_DISPLAY_NAME = "Priya Raman"
OTHER_PILOT_USER_EMAIL = "founder@ravifilms.com"
OTHER_PILOT_USER_DISPLAY_NAME = "Ravi Shankar"


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    test_session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with test_session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def pilot_user(db_session: AsyncSession) -> User:
    """A verified user, standing in for someone who accepted a pilot invitation."""
    user = User(
        email=PILOT_USER_EMAIL,
        display_name=PILOT_USER_DISPLAY_NAME,
        is_email_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def unverified_user(db_session: AsyncSession) -> User:
    """Invited but has not clicked through the verification email yet."""
    user = User(
        email="unverified@sunpictures.com",
        display_name="Unverified Invitee",
        is_email_verified=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def other_pilot_user(db_session: AsyncSession) -> User:
    """A second verified user from a different studio — a non-member for anything
    owned by `pilot_user`, and an owner in their own right when they create their own
    organization."""
    user = User(
        email=OTHER_PILOT_USER_EMAIL,
        display_name=OTHER_PILOT_USER_DISPLAY_NAME,
        is_email_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def anonymous_api_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """A client that asserts no identity — every authenticated route should refuse it."""
    app = create_app()

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
async def api_client(
    anonymous_api_client: AsyncClient, pilot_user: User
) -> AsyncIterator[AsyncClient]:
    """The default client, identified as the pilot user."""
    anonymous_api_client.headers["X-User-Id"] = str(pilot_user.id)
    yield anonymous_api_client


@pytest.fixture
async def unauthenticated_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """A second client asserting no identity, independent of `anonymous_api_client`.

    `api_client` mutates `anonymous_api_client`'s headers in place and yields the same
    object, so a test that requests both `anonymous_api_client` and `api_client`
    receives one client, already carrying `X-User-Id` — not a genuinely anonymous
    caller. Tests that need an authenticated client to set up a resource *and* a
    genuinely header-less client to probe it need this fixture instead.
    """
    app = create_app()

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
async def other_api_client(
    db_session: AsyncSession, other_pilot_user: User
) -> AsyncIterator[AsyncClient]:
    """A second, independent client identified as `other_pilot_user`.

    Deliberately not built on top of `anonymous_api_client`/`api_client`: those are
    function-scoped fixtures, so a test that requested both `api_client` and a
    client built from the same `anonymous_api_client` instance would get back the
    *same* httpx client object with its `X-User-Id` header overwritten by whichever
    fixture ran last. Tests that need two distinct, simultaneously-identified callers
    (e.g. checking one user can't see another's organization) need two distinct
    client instances, sharing only the database.
    """
    app = create_app()

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.headers["X-User-Id"] = str(other_pilot_user.id)
        yield client

    app.dependency_overrides.clear()
