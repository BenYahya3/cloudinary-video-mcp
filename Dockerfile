# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install build deps (needed for cloudinary's optional native bits) then drop them.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast, reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# Copy project metadata first for better layer caching.
COPY pyproject.toml README.md ./
COPY src ./src

# Build the wheel and install into a system venv at /opt/venv.
RUN uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python --no-cache .

ENV PATH="/opt/venv/bin:${PATH}"

EXPOSE 8080
ENV PORT=8080 HOST=0.0.0.0

CMD ["python", "-m", "gdrive_video_mcp.http_app"]
