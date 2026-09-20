# syntax=docker/dockerfile:1.7
# Один backend-образ: api, worker, migrate и служебные команды (app.ops, app.cli).
# WITH_ML=1 добавляет локальные модели (CPU torch, FlagEmbedding); WITH_ML=0 — облегчённая сборка для проверок без моделей.
FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS build
ARG WITH_ML=1
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PROJECT_ENVIRONMENT=/opt/venv PIP_NO_CACHE_DIR=1
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /src
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$WITH_ML" = "1" ]; then uv sync --frozen --no-dev --no-install-project --group ml; \
    else uv sync --frozen --no-dev --no-install-project; fi

FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ARG WITH_ML=1
LABEL org.opencontainers.image.title="doorain-backend" org.opencontainers.image.licenses="proprietary"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH" \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 ANONYMIZED_TELEMETRY=False \
    DOORAIN_DATA_DIR=/data
RUN groupadd --system --gid 10001 doorain && useradd --system --uid 10001 --gid doorain --home-dir /app --shell /usr/sbin/nologin doorain \
    && mkdir -p /data /backups /models && chown -R doorain:doorain /data /backups /models
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY backend/alembic.ini ./
COPY backend/app ./app
COPY backend/prompts ./prompts
COPY backend/migrations ./migrations
COPY fixtures ./fixtures
COPY knowledge_base ./knowledge_base
USER doorain
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=3).status==200 else 1)" || exit 1
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
