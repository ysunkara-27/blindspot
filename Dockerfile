# Blindspot container: built frontend + FastAPI API under one base path (default /blindspot).
# Canonical copy. Hugging Face Spaces need a Dockerfile at the repo root: /Dockerfile is an identical copy
# (keep them in sync: `cp deploy/Dockerfile Dockerfile`). Build context = repo root.
# The image carries NO dataset: deploy/entrypoint.py downloads the processed-data bundle at container start.

# ---------------------------------------------------------------- 1. frontend (Vite) with the public base path
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ARG VITE_BASE_PATH=/
RUN VITE_BASE_PATH=${VITE_BASE_PATH} npm run build

# ---------------------------------------------------------------- 2. API (Python 3.12 + uv, no `ml` extra)
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/

# Hugging Face Spaces run the container as uid 1000 with a writable HOME.
RUN useradd -m -u 1000 user && mkdir -p /data && chown user:user /data
USER user
ENV HOME=/home/user \
    APP=/home/user/app \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/home/user/.cache/uv \
    PYTHONUNBUFFERED=1
WORKDIR $APP

# Runtime deps only (no torch/torchxrayvision: those are the `ml` extra, used by the offline pipeline).
COPY --chown=user pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project && rm -rf $UV_CACHE_DIR

COPY --chown=user backend/ backend/
COPY --chown=user shared/ shared/
COPY --chown=user config/ config/
COPY --chown=user content/ content/
COPY --chown=user deploy/entrypoint.py deploy/entrypoint.py
# curated expert-review queue (case ids + debrief text only; no images)
COPY --chown=user eval/samples/review_queue.jsonl eval/samples/review_queue.jsonl
COPY --from=web --chown=user /web/dist frontend/dist

ENV PATH=$APP/.venv/bin:$PATH \
    PYTHONPATH=$APP \
    BLINDSPOT_DATA_DIR=/data \
    BLINDSPOT_DB_PATH=/data/blindspot.sqlite \
    BLINDSPOT_BASE_PATH=/blindspot \
    BLINDSPOT_SERVE_FRONTEND=1 \
    PORT=7860
EXPOSE 7860
CMD ["python", "deploy/entrypoint.py"]
