# syntax=docker/dockerfile:1.7
# Build context = repo root (docker-compose sets context: .).
# uv workspace: root pyproject.toml + uv.lock + member pyproject.tomls.

FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Cache deps: bind root lock + manifest + every member manifest, sync without source.
COPY pyproject.toml uv.lock ./
COPY apps/backend/pyproject.toml apps/backend/
COPY packages/database/pyproject.toml packages/database/
COPY packages/shared/pyproject.toml packages/shared/
COPY packages/config/pyproject.toml packages/config/

RUN uv sync --locked --no-install-project --package memora-backend

# Copy source, install project + workspace members.
COPY apps/backend apps/backend
COPY packages packages
RUN uv sync --locked --package memora-backend

FROM python:3.12-slim-trixie
ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY --from=builder --chown=nonroot:nonroot /app /app

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "apps/backend"]