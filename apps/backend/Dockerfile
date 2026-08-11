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

FROM python:3.12-slim-trixie AS runtime
ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY --from=builder --chown=nonroot:nonroot /app /app

# Pre-fetch InsightFace buffalo_l weights (~300MB) so runtime doesn't download
# on first face detection. InsightFace expects them at {FACE_MODEL_ROOT}/models/buffalo_l/.
RUN apt-get update && apt-get install -y --no-install-recommends unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/models/insightface/models \
    && curl -fsSL -o /tmp/buffalo_l.zip \
       "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip" \
    && unzip -q /tmp/buffalo_l.zip -d /app/models/insightface/models/buffalo_l \
    && rm /tmp/buffalo_l.zip

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "apps/backend"]