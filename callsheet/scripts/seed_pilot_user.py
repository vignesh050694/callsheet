"""Create a verified pilot user so the onboarding flow can be exercised end to end.

Pilot access is granted out of band — there is no self-serve signup in v1 — so this
script stands in for the invitation that would otherwise create the row.

    uv run python -m scripts.seed_pilot_user --email head@sunpictures.com --name "Priya R"

Prints the user id to pass as the `X-User-Id` header.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.db.session import session_factory
from app.models.user import User


async def seed_pilot_user(email: str, display_name: str) -> User:
    """Idempotent: re-running with the same email returns the existing user."""
    async with session_factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        existing_user = result.scalar_one_or_none()
        if existing_user is not None:
            return existing_user

        user = User(email=email, display_name=display_name, is_email_verified=True)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a verified pilot user.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, dest="display_name")
    arguments = parser.parse_args()

    user = asyncio.run(seed_pilot_user(arguments.email, arguments.display_name))
    print(user.id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
