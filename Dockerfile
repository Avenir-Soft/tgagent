# ── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install . && \
    pip install --no-cache-dir --prefix=/install aiohttp python-dateutil slowapi

# ── Runtime stage ────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# Non-root user
RUN groupadd -r closer && useradd -r -g closer -d /app closer && \
    mkdir -p /app/sessions /app/media_cache /app/static && \
    chown -R closer:closer /app

COPY --chown=closer:closer src/ ./src/
COPY --chown=closer:closer scripts/ ./scripts/
COPY --chown=closer:closer alembic/ ./alembic/
COPY --chown=closer:closer alembic.ini ./
COPY --chown=closer:closer pyproject.toml ./

USER closer

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
