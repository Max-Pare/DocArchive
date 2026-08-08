#!/usr/bin/env bash
set -euo pipefail

echo "Running database migrations..."
alembic upgrade head

echo "Seeding defaults..."
python -m app.seed

echo "Starting API..."
# --proxy-headers is not optional here. The backend publishes no ports, so its only
# possible peer is Caddy; without it request.client.host is Caddy's container IP for
# every request, and the per-IP login limit (slowapi keys on get_remote_address)
# collapses into one global bucket that any 10 logins/minute exhaust for everyone.
# Uvicorn reads the rightmost X-Forwarded-For entry — the address Caddy itself saw —
# so a client-supplied header cannot spoof it.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --proxy-headers --forwarded-allow-ips="*"
