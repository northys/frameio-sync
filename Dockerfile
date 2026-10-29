FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONUNBUFFERED=1 FRAMEIO_SYNC_STATE=/data PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY . .
RUN uv sync --frozen --no-dev
CMD ["sh", "-c", "while true; do frameio-sync sync; sleep 300; done"]
