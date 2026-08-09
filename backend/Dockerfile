# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Without this, Python block-buffers stdout when it isn't a TTY, so the
# migrate-and-seed phase in entrypoint.sh - by far the most failure-prone part of
# a deploy or a restore - is also the least observable. You end up watching
# `docker compose logs` show nothing while alembic works.
ENV PYTHONUNBUFFERED=1

# OCR + PDF rasterization system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-ita \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

COPY . .

# Which commit is this? The first question of every incident, and previously
# unanswerable from a running container. ops/deploy.sh passes the real value.
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}

# /app is root-owned (COPY runs before USER), so appuser cannot write .pyc and
# every cold start re-parses every module. Baking the bytecode in at build time
# fixes that without chowning the source tree - immutable, root-owned app code is
# a feature, and the missing .pyc was its only real cost.
RUN python -m compileall -q /app/app

# Set after compileall, which writes bytecode explicitly. At runtime this only
# stops the import system writing files it has no permission to write anyway.
ENV PYTHONDONTWRITEBYTECODE=1

# The exec bit must be set inside the build: a ZIP download, an NTFS checkout, or
# any copy without -p loses it, and CMD ["./entrypoint.sh"] then fails with exit 126.
RUN chmod +x ./entrypoint.sh

# Non-root user; storage dir is a mounted volume owned to this user at runtime.
RUN useradd -m appuser && mkdir -p /data/files && chown -R appuser:appuser /data
USER appuser

EXPOSE 8000

# python:3.12-slim has no curl/wget, and adding one just for a probe isn't worth a
# layer. start-period covers migrations + seed on a cold boot.
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"]

# entrypoint runs migrations + seed, then serves
CMD ["./entrypoint.sh"]
