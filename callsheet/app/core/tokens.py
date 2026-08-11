"""Capability tokens for invitations (E01-S02).

The raw token is shown once, in the email. Only its hash is persisted, so the database
never holds anything that can be redeemed. SHA-256 with no salt is deliberate: the token
is 32 random bytes, so there is nothing for a salt to defend against, and lookup needs a
deterministic hash to index on.
"""

import hashlib
import secrets

INVITATION_TOKEN_BYTES = 32


def generate_invitation_token() -> str:
    return secrets.token_urlsafe(INVITATION_TOKEN_BYTES)


def hash_invitation_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
