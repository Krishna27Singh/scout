FROM python:3.11-slim AS builder

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /build

RUN python -m venv "$VIRTUAL_ENV"
COPY pyproject.toml ./
COPY backend/ ./backend/
RUN printf '# Scout package metadata\n' > README.md \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/backend" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EMBEDDING_CACHE_DIR="/app/.cache/fastembed" \
    WEB_CONCURRENCY=1 \
    PORT=10000

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system appuser \
    && useradd --system --gid appuser --home-dir /app --no-create-home appuser \
    && mkdir -p /app/.cache/fastembed

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY pyproject.toml /app/pyproject.toml
RUN chown -R appuser:appuser /app

USER appuser
EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT', '10000'), timeout=3).read()"

ENTRYPOINT ["/app/backend/entrypoint.sh"]
