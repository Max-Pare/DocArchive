#!/usr/bin/env bash
# Prove a restored stack is actually usable - not merely that it started.
#
# Run this against the stack produced by ops/restore.sh. The assertion that
# matters is the third one: it downloads real documents and checks their magic
# bytes, which is the only check anywhere in this repo that proves the Fernet key
# IN THE BACKUP still decrypts the archive IN THE BACKUP. Every other check can
# pass on a backup that is worthless.
#
# Usage:
#   ops/verify-backup.sh [--manifest <MANIFEST.txt>] [--sample N]
#
# Env:
#   API_BASE  default http://localhost  (the verify override publishes :8080)

# shellcheck source=ops/lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

API_BASE="${API_BASE:-http://localhost}"
MANIFEST=""
SAMPLE=3

while [ $# -gt 0 ]; do
    case "$1" in
        --manifest) MANIFEST="$2"; shift 2 ;;
        --sample)   SAMPLE="$2";   shift 2 ;;
        *) die "unknown option: $1" ;;
    esac
done

require_cmd curl
require_cmd jq

FAILURES=0
check() {
    local label=$1 ok=$2
    if [ "$ok" = "1" ]; then
        log "PASS  ${label}"
    else
        warn "FAIL  ${label}"
        FAILURES=$((FAILURES + 1))
    fi
}

log "verifying project '$(project_name)' via ${API_BASE}"

# 1. document count -------------------------------------------------------------
DOC_COUNT="$(psql_value 'select count(*) from documents')"
if [ -n "$MANIFEST" ]; then
    EXPECTED="$(awk '/^document_count/ {print $2}' "$MANIFEST")"
    check "document count ${DOC_COUNT} matches manifest ${EXPECTED}" \
          "$([ "$DOC_COUNT" = "$EXPECTED" ] && echo 1 || echo 0)"
else
    log "INFO  ${DOC_COUNT} documents present (no manifest given, not compared)"
fi

[ "$DOC_COUNT" -gt 0 ] || die "the restored archive has no documents - nothing to verify"

# 2. login ----------------------------------------------------------------------
# Credentials come from the restored backend/.env, so this also proves the env/
# half of the backup landed.
#
# `tail -n1`, not the first match: compose's env_file parser is last-key-wins, so
# a file that defines a key twice - which is exactly what CI produces, appending
# real values under the placeholders from .env.example - is served by the LAST
# one. Taking every match made this a two-line string and every login a 401.
env_value() {
    grep -E "^${1}=" "${REPO_ROOT}/backend/.env" | tail -n1 | cut -d= -f2- | tr -d '"'
}
ADMIN_EMAIL="$(env_value ADMIN_EMAIL)"
ADMIN_PASSWORD="$(env_value ADMIN_PASSWORD)"

# Not `curl -f`: a failed login must be reported as a FAIL with the status code,
# not kill the script with a bare "curl: (22)" that says nothing about which of
# the two credentials was wrong.
LOGIN_BODY="$(mktemp)"
LOGIN_CODE="$(curl -sS -m 15 -o "$LOGIN_BODY" -w '%{http_code}' -X POST "${API_BASE}/api/auth/login" \
    -d "username=${ADMIN_EMAIL}" -d "password=${ADMIN_PASSWORD}" || echo 000)"
TOKEN="$(jq -r '.access_token // empty' < "$LOGIN_BODY" 2>/dev/null || true)"
rm -f -- "$LOGIN_BODY"

check "login as ${ADMIN_EMAIL} (HTTP ${LOGIN_CODE})" "$([ -n "$TOKEN" ] && echo 1 || echo 0)"
[ -n "$TOKEN" ] || die "cannot continue without a token"

# 3. documents actually decrypt --------------------------------------------------
# The whole point of the exercise.
ROWS="$(compose exec -T db psql -U docarchive -d docarchive -tAF'|' -c \
    "select id, file_size, mime_type from documents order by random() limit ${SAMPLE}")"

while IFS='|' read -r id size mime; do
    [ -n "$id" ] || continue
    body="$(mktemp)"
    code="$(curl -sS -m 60 -o "$body" -w '%{http_code}' \
        -H "Authorization: Bearer ${TOKEN}" \
        "${API_BASE}/api/documents/${id}/file" || echo 000)"
    got="$(stat -c%s "$body")"

    magic_ok=0
    case "$mime" in
        application/pdf) head -c4 "$body" | grep -q '%PDF' && magic_ok=1 ;;
        image/png)       [ "$(head -c8 "$body" | xxd -p)" = "89504e470d0a1a0a" ] && magic_ok=1 ;;
        image/jpeg)      [ "$(head -c3 "$body" | xxd -p)" = "ffd8ff" ] && magic_ok=1 ;;
        # Anything else: a plausible size is the best signal available, and a
        # failed decrypt yields a 500 with no body, which the size check catches.
        *)               [ "$got" -gt 0 ] && magic_ok=1 ;;
    esac

    check "document ${id}: HTTP ${code}, ${got}/${size} bytes, ${mime} magic" \
          "$([ "$code" = "200" ] && [ "$got" = "$size" ] && [ "$magic_ok" = "1" ] && echo 1 || echo 0)"
    rm -f -- "$body"
done <<< "$ROWS"

# 4. full-text search still works -------------------------------------------------
# Proves the ix_documents_fts GIN index survived pg_restore. It is built by raw
# SQL in migration 0001 and is invisible to alembic autogenerate, so it is
# exactly the kind of thing a restore quietly loses.
WORD="$(psql_value "select regexp_replace(split_part(btrim(ocr_text), ' ', 1), '[^[:alnum:]]', '', 'g') from documents where length(btrim(coalesce(ocr_text,''))) > 20 limit 1")"
if [ -n "$WORD" ]; then
    HITS="$(curl -fsS -m 15 -H "Authorization: Bearer ${TOKEN}" \
        "${API_BASE}/api/documents?q=${WORD}" | jq 'length')"
    check "full-text search for '${WORD}' returned ${HITS} hit(s)" \
          "$([ "${HITS:-0}" -ge 1 ] && echo 1 || echo 0)"
else
    warn "SKIP  no OCR'd document to search for"
fi

if [ "$FAILURES" -eq 0 ]; then
    log "all checks passed"
else
    die "${FAILURES} check(s) failed - THIS BACKUP IS NOT TRUSTWORTHY"
fi
