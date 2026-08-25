FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN pip install uv && uv sync --frozen || pip install -e .
COPY . .
ENV LIVE_TRADING_ENABLED=false
CMD ["sh", "-c", "python -m alembic -c alembic.ini upgrade head && uvicorn crypto_trader.api.app:app --host 0.0.0.0 --port 8000"]
