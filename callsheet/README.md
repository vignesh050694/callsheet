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

- The `Organization` model covers E01-S01. Memberships, titles, and the collection layer are not built yet.
- `MONID_API_KEY` is reserved for the E03 collection layer and is unused so far.
