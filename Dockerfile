# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build deps (psycopg binary needs gcc + libc headers).
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

# Install the pinned, reproducible dependency graph first (best layer caching:
# this only invalidates when requirements.lock changes, not on every app edit).
# requirements.lock is `pip freeze --exclude-editable` against the project's
# pinned manifest — the editable self-reference `pip freeze` would otherwise
# emit for this very package (`-e git+ssh://...#egg=vivi_api`) is stripped,
# because a Docker build has no SSH key to clone it with.
COPY requirements.lock ./
RUN pip install --upgrade pip && pip install -r requirements.lock

# Now copy the project itself and install it with no further dependency
# resolution (everything it needs is already satisfied by the lock above).
# `scripts/` must ship in the image — `scripts.seed_colsubsidio` is what
# populates the demo data once the container is running on Fly.
COPY pyproject.toml README.md ./
COPY app ./app
COPY scripts ./scripts

RUN pip install --no-deps "."

EXPOSE 8000

# Managed platforms (Railway, Render, Heroku, Cloud Run) assign the port at
# runtime through $PORT and route only to that port — a container listening on a
# hardcoded 8000 fails their health check and the deploy is marked dead. The
# shell form is required so $PORT is expanded; the fallback keeps `docker run`
# and docker-compose working unchanged locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]