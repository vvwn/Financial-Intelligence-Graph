# FIG backend image.
#
# Build from the REPO ROOT (needs backend/ and database/ for migrations):
#   docker build -f deploy/backend.Dockerfile -t fig-api:0.1.0 .
#
# The image does not carry .env; configuration comes from environment variables.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/

# Dependencies first so the layer caches across code changes.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/app ./app
COPY backend/alembic.ini ./alembic.ini
COPY database/migrations ./migrations

# Container layout differs from the repo layout, so point the app at the copies.
ENV ALEMBIC_INI_PATH=/app/alembic.ini \
    MIGRATIONS_PATH=/app/migrations \
    PYTHONPATH=/app

RUN useradd --create-home --uid 10001 fig
USER fig

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)"

CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
