#!/usr/bin/env bash
# Restore the DocArchive stack from a backup produced by ops/backup.sh.
#
# This is the procedure that did not exist anywhere in the repo. It encodes the
# correct order rather than describing it, because the order is the part people
# get wrong at 2am.
#
# Usage:
#   ops/restore.sh --yes-destroy-current-data <backup.tar.age>
#
# Rehearse without risking anything real:
#   COMPOSE_PROJECT_NAME=docarchive-verify ops/restore.sh \
#       --yes-destroy-current-data /var/backups/docarchive/<stamp>.tar.age
#
# That addresses a completely separate set of Docker volumes. It is the reason
# every volume name in lib.sh is built from the project name.
#
# Env:
#   AGE_IDENTITY  path to the age private key (default ~/.config/age/docarchive.txt)

# shellcheck source=ops/lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

CONFIRMED=0
ARCHIVE=""
for arg in "$@"; do
    case "$arg" in
        --yes-destroy-current-data) CONFIRMED=1 ;;
        -*) die "unknown option: $arg" ;;
        *)  ARCHIVE="$arg" ;;
    esac
done

[ -n "$ARCHIVE" ] || die "usage: $0 --yes-destroy-current-data <backup.tar.age>"
[ -f "$ARCHIVE" ] || die "no such backup: $ARCHIVE"
[ "$CONFIRMED" -eq 1 ] || die "refusing to run without --yes-destroy-current-data (this REPLACES project '$(project_name)')"

AGE_IDENTITY="${AGE_IDENTITY:-${HOME}/.config/age/docarchive.txt}"
require_cmd docker
require_cmd age "sudo pacman -S age"
[ -f "$AGE_IDENTITY" ] || die "no age identity at ${AGE_IDENTITY}. It lives in your password manager - see ops/RUNBOOK.md."

WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT

log "restoring project '$(project_name)' from ${ARCHIVE}"

# 1. decrypt and check integrity ------------------------------------------------
log "decrypting"
age -d -i "$AGE_IDENTITY" < "$ARCHIVE" | tar -C "$WORK" -xf -
( cd "$WORK" && sha256sum -c SHA256SUMS --quiet ) || die "checksum mismatch - this backup is corrupt"

BACKUP_ALEMBIC="$(cat "${WORK}/alembic_version.txt")"
log "backup manifest:"
sed 's/^/    /' "${WORK}/MANIFEST.txt" >&2

# 2. stop the stack, WITHOUT -v -------------------------------------------------
# `down -v` here would destroy the volumes we are about to replace anyway, but it
# would also destroy them if any later step failed. Never -v.
log "stopping stack"
compose down --remove-orphans || true

# 3. replace volumes ------------------------------------------------------------
log "restoring file_data"
volume_from_tar "$(volume_name file_data)" "${WORK}/file_data.tar.gz"
if [ -f "${WORK}/caddy_data.tar.gz" ]; then
    log "restoring caddy_data"
    volume_from_tar "$(volume_name caddy_data)" "${WORK}/caddy_data.tar.gz"
fi

# The database volume is recreated empty and repopulated from the dump, rather
# than restored as a file tree: a dump is portable across Postgres patch levels,
# a raw data directory is not.
docker volume rm -f "$(volume_name db_data)" >/dev/null 2>&1 || true
docker volume create "$(volume_name db_data)" >/dev/null

# 4. bring up the database alone ------------------------------------------------
log "starting database"
compose up -d db
for _ in $(seq 1 60); do
    compose exec -T db pg_isready -U docarchive >/dev/null 2>&1 && break
    sleep 2
done
compose exec -T db pg_isready -U docarchive >/dev/null 2>&1 \
    || die "database did not become ready within 120s"

# 5. load the dump --------------------------------------------------------------
log "restoring database"
compose exec -T db pg_restore --clean --if-exists --no-owner \
    -U docarchive -d docarchive < "${WORK}/db.dump"

# 6. assert the schema version --------------------------------------------------
RESTORED_ALEMBIC="$(psql_value 'select version_num from alembic_version')"
[ "$RESTORED_ALEMBIC" = "$BACKUP_ALEMBIC" ] \
    || die "restored alembic_version '${RESTORED_ALEMBIC}' != manifest '${BACKUP_ALEMBIC}'"

REPO_HEADS="$( ( cd "${REPO_ROOT}/backend" && alembic heads 2>/dev/null ) | awk '{print $1}' | tr -d '[:space:]' || true)"
if [ -z "$REPO_HEADS" ]; then
    warn "could not read 'alembic heads' from the checkout; skipping the code-vs-data check"
elif [ "$REPO_HEADS" = "$RESTORED_ALEMBIC" ]; then
    log "schema matches the checked-out code (${RESTORED_ALEMBIC})"
else
    # Repo ahead of the backup is normal: migrate forward and say so.
    # Repo BEHIND the backup is the silent-corruption case - newer data under
    # older code - and is the one situation where stopping is the right answer.
    log "checkout is at ${REPO_HEADS}, backup is at ${RESTORED_ALEMBIC}"
    log "the backend will run 'alembic upgrade head' on boot; if the checkout is OLDER than the backup, abort now (Ctrl-C) and check out the matching commit"
fi

# 7. bring the rest up ----------------------------------------------------------
log "starting the rest of the stack"
compose up -d --wait

log "restore complete. Run ops/verify-backup.sh to prove the documents actually decrypt."
