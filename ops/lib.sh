#!/usr/bin/env bash
# Shared helpers for the ops scripts. Sourced, never executed.
#
# Everything here is deliberately boring. This is the code that runs when the
# archive is already in trouble, so it favours loud failure over cleverness.

set -euo pipefail

# Repo root, resolved from this file rather than from the caller's cwd, so the
# scripts work when invoked by systemd, by cron, or from anywhere on the disk.
#
# The guard is not paranoia. Sourced from a non-bash shell, BASH_SOURCE is empty,
# dirname yields ".", and REPO_ROOT silently becomes the *parent* directory - so
# project_name() returns the wrong project and every volume_name() addresses
# volumes that belong to something else. In restore.sh that is a `docker volume
# rm` against the wrong stack. Fail loudly instead.
if [ -z "${BASH_SOURCE[0]:-}" ]; then
    printf 'FATAL: ops/lib.sh must be sourced from bash (BASH_SOURCE is unset)\n' >&2
    exit 1
fi
OPS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${OPS_DIR}/.." && pwd)"
[ -f "${REPO_ROOT}/docker-compose.yml" ] \
    || { printf 'FATAL: %s is not the DocArchive repo root\n' "$REPO_ROOT" >&2; exit 1; }
export OPS_DIR REPO_ROOT

log()  { printf '%s  %s\n'  "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2; }
warn() { printf '%s  WARN: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2; }
die()  { printf '%s  FATAL: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2; exit 1; }

require_cmd() {
    local cmd=$1 hint=${2:-}
    command -v "$cmd" >/dev/null 2>&1 && return 0
    if [ -n "$hint" ]; then
        die "'$cmd' is not installed. Install it with: $hint"
    fi
    die "'$cmd' is not installed."
}

# Compose project name. Docker derives it from the directory name (lowercased,
# stripped of anything outside [a-z0-9_-]) unless COMPOSE_PROJECT_NAME is set.
#
# Every volume name in this file is built from this, which is what makes a
# rehearsal safe: COMPOSE_PROJECT_NAME=docarchive-verify addresses a completely
# separate set of volumes and cannot touch the real ones.
project_name() {
    if [ -n "${COMPOSE_PROJECT_NAME:-}" ]; then
        printf '%s' "$COMPOSE_PROJECT_NAME"
        return
    fi
    basename "$REPO_ROOT" | tr '[:upper:]' '[:lower:]' | tr -cd '[:alnum:]_-'
}

volume_name() {
    printf '%s_%s' "$(project_name)" "$1"
}

compose() {
    ( cd "$REPO_ROOT" && docker compose "$@" )
}

# Tar a named volume out to a gzip on the host, via a throwaway container.
#
# Mounting :ro means a bug here cannot damage the source, and going through a
# container means we never touch /var/lib/docker/volumes directly - that path is
# root-only and is not a supported interface.
volume_to_tar() {
    local volume=$1 out=$2
    docker volume inspect "$volume" >/dev/null 2>&1 \
        || die "volume '$volume' does not exist (wrong COMPOSE_PROJECT_NAME?)"
    docker run --rm \
        -v "${volume}:/src:ro" \
        -v "$(dirname -- "$out"):/dst" \
        alpine:3 tar -C /src -czf "/dst/$(basename -- "$out")" .
}

# Restore a gzip into a named volume, replacing whatever is there.
volume_from_tar() {
    local volume=$1 src=$2
    [ -f "$src" ] || die "archive '$src' not found"
    docker volume rm -f "$volume" >/dev/null 2>&1 || true
    docker volume create "$volume" >/dev/null
    docker run --rm \
        -v "${volume}:/dst" \
        -v "$(dirname -- "$src"):/src:ro" \
        alpine:3 tar -C /dst -xzf "/src/$(basename -- "$src")"
}

psql_value() {
    compose exec -T db psql -U docarchive -d docarchive -tAc "$1" | tr -d '[:space:]'
}

# The private key never lives on this machine, so anything encrypted here can
# only be opened by whoever holds the identity in the password manager.
RECIPIENT_FILE="${RECIPIENT_FILE:-${OPS_DIR}/backup-recipient.txt}"

require_recipient() {
    require_cmd age "sudo pacman -S age   (or: apt install age / brew install age)"
    [ -f "$RECIPIENT_FILE" ] \
        || die "no recipient file at ${RECIPIENT_FILE}. See ops/RUNBOOK.md - 'First-time setup'."
    grep -q '^age1' "$RECIPIENT_FILE" \
        || die "${RECIPIENT_FILE} holds no age public key (expected a line starting 'age1'). See ops/RUNBOOK.md."
}
