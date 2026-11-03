FROM node:24.14.1-bookworm-slim AS frontend
WORKDIR /build/web
RUN npm install --global npm@11.18.0
COPY web/package.json web/package-lock.json web/.npmrc ./
RUN npm ci --no-audit
COPY web/index.html web/tsconfig.json web/vite.config.ts ./
COPY web/src ./src
COPY web/public ./public
RUN npm run build

FROM python:3.12.14-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    libegl1 libgl1 libglu1-mesa libgomp1 libx11-6 libxext6 libxrender1 libsm6 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/usr/local \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app MUJOCO_GL=egl PORT=7860
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --all-extras --no-dev --no-install-project --inexact --no-cache
COPY app ./app
COPY scripts/deploy_modal.py ./scripts/deploy_modal.py
COPY THIRD_PARTY_NOTICES.md ./
COPY --from=frontend /build/web/dist ./web/dist
RUN useradd --create-home --uid 10001 workspace && mkdir /data && chown workspace /data
USER workspace
CMD ["sh", "-c", "exec python -m uvicorn app.hosted:create_app --factory --host 0.0.0.0 --port ${PORT:-7860} --workers 1 --no-access-log"]
