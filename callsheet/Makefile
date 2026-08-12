.PHONY: install dev db-up db-down migrate revision seed-user reprocess test lint format typecheck check

install:
	uv sync

dev:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

migrate:
	uv run alembic upgrade head

# usage: make revision m="add titles table"
revision:
	uv run alembic revision --autogenerate -m "$(m)"

# usage: make seed-user email=head@sunpictures.com name="Priya R"
seed-user:
	uv run python -m scripts.seed_pilot_user --email "$(email)" --name "$(name)"

# usage: make reprocess title=<uuid> [from=2026-07-01] [until=2026-08-11]
# Recomputes derived fields from stored payloads. Spends nothing on collection.
reprocess:
	uv run python -m scripts.reprocess_title --title-id "$(title)" \
		$(if $(from),--from "$(from)") $(if $(until),--until "$(until)")

test:
	uv run pytest -q

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy app

check: lint typecheck test
