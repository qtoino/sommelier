# Self-hosted Sommelier: the web app only. The content pipeline runs on the host.
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY alembic.ini repos.toml ./
COPY backend/ backend/
COPY fixtures/ fixtures/
COPY data/ data/
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist frontend/dist
ENV PATH="/app/.venv/bin:$PATH" SOMMELIER_DB=/var/lib/sommelier/sommelier.db
RUN mkdir -p /var/lib/sommelier
EXPOSE 8000
CMD ["sh", "-c", "python -m alembic upgrade head && python -m sommelier import --if-empty data/items.jsonl fixtures/seed.jsonl && exec python -m uvicorn sommelier.app:app --host 0.0.0.0 --port 8000"]
