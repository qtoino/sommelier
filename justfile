set windows-shell := ["pwsh", "-NoLogo", "-NoProfile", "-Command"]
set dotenv-load
export PLAYWRIGHT_BROWSERS_PATH := justfile_directory() / ".playwright-browsers"

# API on :8000 + Vite on :5173 (open http://localhost:5173)
dev:
    uv run python -m alembic upgrade head
    uv run python scripts/dev.py

test:
    uv run pytest
    cd frontend; npm test

lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy
    cd frontend; npm run lint

fmt:
    uv run ruff format .
    uv run ruff check --fix .

# load hand-written fixtures into the DB
seed:
    uv run python -m alembic upgrade head
    uv run python -m sommelier import fixtures/seed.jsonl

# browser smoke test of the core loop
e2e:
    cd frontend; npm run build
    uv run playwright install chromium
    uv run pytest -m e2e
