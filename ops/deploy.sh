#!/usr/bin/env bash
# Upgrade the running stack to the current main.
#
# Step 1 is a backup, and that is the entire reason this script exists rather
# than a list of commands in a document. A migration that has already run is NOT
# undone by `git checkout` - the only way back is the dump taken before it.
#
# Env:
#   SKIP_BACKUP=1   only when you have just taken one by hand

# shellcheck source=ops/lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_cmd docker
require_cmd git

cd "$REPO_ROOT"

if [ "${SKIP_BACKUP:-0}" = "1" ]; then
    warn "SKIP_BACKUP=1 - deploying without a fresh restore point"
else
    log "step 1/5: backup"
    "${OPS_DIR}/backup.sh"
fi

log "step 2/5: fetch"
git pull --ff-only

GIT_SHA="$(git rev-parse HEAD)"
export GIT_SHA
log "deploying ${GIT_SHA}"

log "step 3/5: build"
compose build

log "step 4/5: up"
compose up -d --wait --wait-timeout 300

# ---------------------------------------------------------------------------
# step 5: prove it actually came up
# ---------------------------------------------------------------------------
log "step 5/5: post-deploy checks"
FAILURES=0

# A crash-looping container reports "running" between restarts, so the restart
# count is the signal, not the state. This is the guard for the exit-126 outage
# where the app never ran once and the stack still looked alive.
for svc in db backend frontend proxy; do
    cid="$(compose ps -q "$svc" 2>/dev/null || true)"
    if [ -z "$cid" ]; then
        warn "service ${svc} has no container"; FAILURES=$((FAILURES + 1)); continue
    fi
    restarts="$(docker inspect -f '{{.RestartCount}}' "$cid")"
    if [ "$restarts" != "0" ]; then
        warn "service ${svc} has restarted ${restarts} time(s)"
        docker logs --tail 40 "$cid" >&2 || true
        FAILURES=$((FAILURES + 1))
    fi
done

curl -fsS -m 10 "${API_BASE:-http://localhost}/api/health" >/dev/null \
    || { warn "/api/health did not answer"; FAILURES=$((FAILURES + 1)); }

DB_HEAD="$(psql_value 'select version_num from alembic_version' || true)"
# From the running container, not a host venv: that is the code that just ran the
# migration, and it needs no Python on the host.
REPO_HEAD="$(compose exec -T backend alembic heads 2>/dev/null \
    | awk '/^[0-9a-f]+ ?/ {print $1; exit}' | tr -d '[:space:]' || true)"
if [ -n "$REPO_HEAD" ] && [ "$DB_HEAD" != "$REPO_HEAD" ]; then
    warn "alembic_version is ${DB_HEAD} but the checkout is at ${REPO_HEAD} - migrations did not complete"
    FAILURES=$((FAILURES + 1))
fi

[ "$FAILURES" -eq 0 ] || die "${FAILURES} post-deploy check(s) failed. To roll back: see ops/RUNBOOK.md"

log "deployed ${GIT_SHA} (schema ${DB_HEAD})"
