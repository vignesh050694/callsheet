# Callsheet — Backend

FastAPI backend for the Agentic Social Media Control Centre.

## Requirements

- Python 3.12+ (`.python-version` pins 3.13; `uv` will fetch it)
- [uv](https://docs.astral.sh/uv/)
- Docker (for local Postgres) — or point `DATABASE_URL` at any Postgres you already run

## Getting started

```bash
cp .env.example .env
make install        # uv sync
make db-up          # docker compose up -d postgres
make migrate        # alembic upgrade head
make dev            # uvicorn on :8000, reload enabled
```

- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/api/v1/health

`make test` needs neither Postgres nor Docker — the suite runs against in-memory SQLite.

## Commands

| Command | What it does |
|---|---|
| `make install` | Sync dependencies into `.venv` |
| `make dev` | Run the dev server with reload |
| `make db-up` / `make db-down` | Start/stop local Postgres |
| `make migrate` | Apply migrations to head |
| `make revision m="add titles"` | Autogenerate a migration from model changes |
| `make seed-user email=... name="..."` | Create a verified pilot user for testing (prints user id) |
| `make test` | pytest |
| `make lint` / `make format` | ruff |
| `make typecheck` | mypy |
| `make check` | lint + typecheck + test |

## Layout

```
app/
  main.py                    app factory, middleware + exception handler wiring
  core/
    config.py                all settings, read once from env
    logging_config.py        structlog setup, secret redaction
    exceptions.py            domain errors (services raise these, not HTTP errors)
  middleware/
    request_logging.py       request id, start/end logs, duration
  api/
    deps.py                  shared FastAPI dependencies
    v1/router.py             the v1 surface — register new route modules here
    v1/routes/               controllers: parse, call one service, shape response
  services/                  business rules + transaction boundaries
  repositories/              database queries only
  models/                    SQLAlchemy tables
  schemas/                   Pydantic request/response DTOs
  db/session.py              engine + per-request session dependency
alembic/                     migrations
scripts/                     one-off utilities (seed_pilot_user.py for testing)
tests/                       pytest, SQLite-backed
```

### Layering rules

Requests flow **controller → service → repository**, one direction only.

- **Controllers** validate the request shape, call one service method, and map the result to a response. No business rules, no ORM calls.
- **Services** own every rule, orchestrate across repositories, and decide transaction boundaries. They raise `DomainError` subclasses and know nothing about status codes — `app/main.py` maps errors to HTTP in one place.
- **Repositories** run queries and return rows. No decisions, no HTTP.

### Logging

`RequestLoggingMiddleware` logs `request.start` and `request.end` for every request, with a correlation id (echoed back as `X-Request-ID`), the route, the status, and the duration from a monotonic clock. Levels follow outcome: 5xx → `error`, 4xx → `warning`, otherwise `info`.

In application code use `structlog.get_logger(__name__)`, never `print`. `LOG_LEVEL` and `LOG_FORMAT` (`json` in deployed environments, `console` locally) are environment-driven. Fields named like secrets are redacted before they reach any sink.

## Adding a feature

For a new resource — say titles (E02) — add one file per layer and register the route:

1. `app/models/title.py` — the table, then export it from `app/models/__init__.py` so Alembic sees it
2. `app/schemas/title.py` — request/response DTOs
3. `app/repositories/title_repository.py` — queries
4. `app/services/title_service.py` — rules
5. `app/api/v1/routes/titles.py` — routes
6. Register in `app/api/v1/router.py`, add a dependency in `app/api/deps.py`
7. `make revision m="add titles table" && make migrate`

`organizations` is the reference implementation of this shape end to end.

## Notes

- **E01-S01 (organizations and memberships)** is built. Routes require caller identity via `X-User-Id` header (temporary seam for session layer). Ownership is a membership row with role `owner`, not a column on organizations. `GET /api/v1/me` returns the signed-in user and their memberships; empty list routes first-time users to onboarding. `POST /api/v1/organizations` creates org and owner membership in one transaction and requires verified email (403 if not verified).
- **E01-S02 (invite teammate with role)** is built. Membership roles are `owner` and `viewer`. Viewers have read-only access to an organization; owners can manage members and change settings. All role checks are enforced server-side.
  - New endpoints (all require `X-User-Id` header):
    - `GET /api/v1/organizations/{organization_id}/members` — members plus pending invitations. Any member may read it. Returns `{members: [{user_id, email, display_name, role, joined_at}], pending_invitations: [{id, email, role, status, last_sent_at, created_at}]}`. Pending invitations never carry the token.
    - `POST /api/v1/organizations/{organization_id}/invitations` — owner only. Body: `{email, role}`. Returns invitation and a raw `token`, returned exactly once.
    - `POST /api/v1/invitations/{invitation_id}/resend` — owner only. Issues a new token; the previous link stops working.
    - `DELETE /api/v1/invitations/{invitation_id}` — owner only. Cancels a pending invitation.
    - `POST /api/v1/invitations/accept` — body `{token}`. Creates membership with the invited role. Caller's email must match the invitation's, and email must be verified.
  - Invitation tokens: only SHA-256 hash is stored in the database; the plaintext token is returned once when created or resent.
  - Status codes: non-member acting on an org gets 404; viewer attempting owner-only action gets 403; unauthenticated gets 401; duplicate or racing writes get 409.
  - Limitations: no mail transport (acceptance link is shown in the owner's UI); invitations do not expire.
  - New dependency: `email-validator` (for Pydantic EmailStr).
- **E02-S01 (title setup with rich identity)** is built. A title's identity set is stored as rows in `title_terms`, one per term, with a `term_type` of `alias`, `hashtag`, `cast`, `director`, or `music_director`. Bare title queries are the known failure case (collection against the name alone returns its namesakes, not the film); the anchored form — name plus aliases, hashtags, and cast/crew — is what finds the film.
  - New tables: `titles` (and auto-generated migration `alembic/versions/4e0b7c9a2d15_create_titles_and_title_terms_tables.py`); `title_terms` with a unique constraint on `(title_id, term_type, normalized_value)` to dedupe within each term kind.
  - Identity terms are normalised for comparison: NFKC, leading hashes stripped, whitespace collapsed, casefolded. The value the studio typed is preserved for display.
  - New endpoints (all require `X-User-Id` header):
    - `POST /api/v1/organizations/{organization_id}/titles` — owner only. Body: `{name, aliases[], hashtags[], lead_cast[], directors[], music_directors[], poster_url}`. Returns the title with `terms`, `collection_terms`, and `has_anchor_term`.
    - `GET /api/v1/organizations/{organization_id}/titles` — any member. Paginated. Returns `{items: [titles], total, limit, offset}`.
    - `GET /api/v1/titles/{title_id}` — any member of the owning organization.
  - The anchor rule: a title name under 4 characters must include at least one cast or crew term ("anchor term"), otherwise creation is refused with 422. A hashtag or alias does not count. Enforced server-side in `TitleService`; the setup form also blocks submission and explains why.
  - Status codes: viewer attempting to create a title gets 403; non-member gets 404 on all title routes (title existence is deliberately not leaked); unauthenticated gets 401; a term longer than 300 characters gets 422. Duplicate terms within a type are deduped on the way in rather than rejected; the unique constraint is a backstop that would surface as 409.
  - Limitations:
    - Variation selectors (U+FE00–U+FE0F) are Unicode category Mn, so they are not recognised as invisible and can be supplied as a cast term to satisfy the anchor rule. Tracked as E02-S06.
    - The anchor rule counts characters rather than grapheme clusters, so it is inconsistent for Devanagari: "सीता" and "काका" (two aksharas) are accepted without an anchor term while "राधे" (also two aksharas) is refused. Tracked as E02-S07.
- The collection layer (E03) is not yet built. `collection_terms` describes the set collection is intended to query.
- `MONID_API_KEY` is reserved for the E03 collection layer and is unused so far.
