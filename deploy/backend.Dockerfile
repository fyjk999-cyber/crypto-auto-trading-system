# Cloud backend image (single canonical PAPER runtime).
# Build context: repository root (docker build -f deploy/backend.Dockerfile .)
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: curl for container healthcheck probes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install the canonical application from pyproject.toml truth.
COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-deps . && pip install -e ".[dev]" --no-deps 2>/dev/null || pip install .

# Re-install full dependency set (previous layer minimized layers).
RUN pip install .

COPY scripts/wait_for_postgres.py ./scripts/wait_for_postgres.py

# Secrets are NEVER baked into the image: mounted at runtime (see compose).
ENV LLM_SECRET_STORE_PATH=/app/secrets/.llm-secrets.json \
    LLM_MASTER_KEY_PATH=/app/secrets/.llm-master-key

# One canonical runtime: NO --workers, NO --reload. Alembic migrations run
# in the entrypoint before the API (and the auto-started trading runtime).
ENTRYPOINT ["./deploy/entrypoint-backend.sh"]
