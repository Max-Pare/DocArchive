#!/usr/bin/env bash
# Take a complete, encrypted, verifiable backup of the DocArchive stack.
#
# Produces one file: ${BACKUP_DIR}/<UTC stamp>.tar.age
#
# Why encrypted, and why that is not optional: documents.ocr_text is stored in
# Postgres in CLEARTEXT, so the database dump contains the full text of every
# medical document in the archive. The dump is exactly as sensitive as the
# encrypted file volume, and the old README treated only the files as secret.
#
# Encryption uses an age PUBLIC key committed to the repo, so this script needs
# no secret in order to run unattended. Only restore needs the private key, which
# lives solely in the operator's password manager.
#
# Env:
#   BACKUP_DIR            where to write            (default /var/backups/docarchive)
#   RETENTION_DAYS        prune older than this     (default 14)
#   RCLONE_REMOTE         if set, copy offsite via rclone
#   HEALTHCHECK_PING_URL  if set, GET on success (dead-man's switch)
#   COMPOSE_PROJECT_NAME  address a non-default stack

# shellcheck source=ops/lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

BACKUP_DIR="${BACKUP_DIR:-/var/backups/docarchive}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

require_cmd docker
require_recipient

STAMP="$(date -u '+%Y-%m-%dT%H-%M-%SZ')"
FINAL="${BACKUP_DIR}/${STAMP}.tar.age"

# Everything is assembled under .partial and only renamed on success. A partial
# backup that looks complete is worse than no backup at all: it is the one that
# gets trusted on the day it matters.
WORK="${BACKUP_DIR}/${STAMP}.partial"
trap 'rm -rf -- "$WORK" "${WORK}.sums"' EXIT

mkdir -p -- "$WORK/env"

log "backing up project '$(project_name)' -> ${FINAL}"

compose ps --status running --services 2>/dev/null | grep -qx db \
    || die "the 'db' service is not running; start the stack before backing up"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# -T is load-bearing: without it `docker compose exec` allocates a TTY and
# mangles the dump stream. The old README.md command omitted it.
# -Fc gives compression plus selective/parallel restore.
log "dumping database"
compose exec -T db pg_dump -U docarchive -d docarchive -Fc --clean --if-exists \
    > "${WORK}/db.dump"

# The single field that makes a restore *verifiable* rather than hopeful: it lets
# restore.sh refuse to put a newer database under older code.
psql_value 'select version_num from alembic_version' > "${WORK}/alembic_version.txt"

DOC_COUNT="$(psql_value 'select count(*) from documents')"

# ---------------------------------------------------------------------------
# Volumes
# ---------------------------------------------------------------------------
log "archiving file_data"
volume_to_tar "$(volume_name file_data)" "${WORK}/file_data.tar.gz"

# Not data, but it holds the ACME account key. Losing it is survivable (Caddy
# re-issues) right up until re-issuing repeatedly during a disaster recovery
# trips a Let's Encrypt rate limit, which is the worst possible moment.
log "archiving caddy_data"
volume_to_tar "$(volume_name caddy_data)" "${WORK}/caddy_data.tar.gz"

# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------
# Includes FILE_ENCRYPTION_KEY. Correct only because the whole tree is encrypted
# to the age recipient below - a backup of ciphertext without its key is not a
# backup, it is a very tidy way of losing everything.
for f in .env backend/.env; do
    [ -f "${REPO_ROOT}/${f}" ] && cp -- "${REPO_ROOT}/${f}" "${WORK}/env/$(echo "$f" | tr '/' '_')"
done

# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
{
    echo "created_utc      $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "project          $(project_name)"
    echo "host             $(hostname)"
    echo "git_sha          $(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "git_dirty        $(git -C "$REPO_ROOT" status --porcelain 2>/dev/null | head -c1 | grep -q . && echo yes || echo no)"
    echo "alembic_version  $(cat "${WORK}/alembic_version.txt")"
    echo "document_count   ${DOC_COUNT}"
    echo "file_data_bytes  $(stat -c%s "${WORK}/file_data.tar.gz")"
    echo "pg_dump_version  $(compose exec -T db pg_dump --version | tr -d '\r')"
    # Recording digests beats pinning them: it answers "what exactly was running
    # the day it worked" without freezing you out of base-image security patches.
    for svc in db backend frontend proxy; do
        cid="$(compose ps -q "$svc" 2>/dev/null || true)"
        [ -n "$cid" ] || continue
        img="$(docker inspect -f '{{.Image}}' "$cid")"
        digest="$(docker inspect -f '{{index .RepoDigests 0}}' "$img" 2>/dev/null || echo "$img")"
        echo "image_${svc}  ${digest}"
    done
} > "${WORK}/MANIFEST.txt"

# Written outside the tree, then moved in: generating it in place would have find
# racing the redirect that creates its own output file.
( cd "$WORK" && find . -type f -print0 | sort -z | xargs -0 sha256sum ) > "${WORK}.sums"
mv -- "${WORK}.sums" "${WORK}/SHA256SUMS"

# ---------------------------------------------------------------------------
# Seal
# ---------------------------------------------------------------------------
log "encrypting"
mkdir -p -- "$BACKUP_DIR"
tar -C "$WORK" -cf - . | age -R "$RECIPIENT_FILE" > "${FINAL}.partial"
mv -- "${FINAL}.partial" "$FINAL"
chmod 600 -- "$FINAL"

log "wrote ${FINAL} ($(stat -c%s "$FINAL") bytes, ${DOC_COUNT} documents)"

# ---------------------------------------------------------------------------
# Retention, offsite, dead-man's switch
# ---------------------------------------------------------------------------
# Flat age-based pruning on purpose. A grandfather-father-son scheme is
# complexity in the one script that cannot afford a bug.
find "$BACKUP_DIR" -maxdepth 1 -name '20*.tar.age' -type f -mtime "+${RETENTION_DAYS}" -print -delete >&2 || true

if [ -n "${RCLONE_REMOTE:-}" ]; then
    log "copying offsite to ${RCLONE_REMOTE}"
    rclone copy "$FINAL" "$RCLONE_REMOTE"
else
    warn "RCLONE_REMOTE is not set - this backup is on the same disk as the data it backs up"
fi

# A backup system that silently stopped four months ago is indistinguishable
# from no backup system, and that is how these actually fail.
if [ -n "${HEALTHCHECK_PING_URL:-}" ]; then
    curl -fsS -m 10 "$HEALTHCHECK_PING_URL" >/dev/null || warn "dead-man's-switch ping failed"
else
    warn "HEALTHCHECK_PING_URL is not set - nothing will notice if backups stop"
fi

log "done"
