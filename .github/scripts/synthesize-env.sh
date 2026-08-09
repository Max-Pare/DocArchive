#!/usr/bin/env bash
# Build .env and backend/.env for a throwaway CI stack, from the committed
# examples.
#
# Shared by the `smoke` and `restore rehearsal` jobs. It exists as a script
# rather than an inline step because the second copy of a 40-line block is where
# the two quietly stop agreeing.
#
# Following the README's Quick start LITERALLY is the point: if .env.example or
# backend/.env.example ever stops being sufficient to boot the stack, CI goes red,
# so documentation drift becomes a build failure instead of a support
# conversation.
#
# Env in:  SMOKE_ADMIN_EMAIL, SMOKE_ADMIN_PASSWORD

set -euo pipefail

: "${SMOKE_ADMIN_EMAIL:?set SMOKE_ADMIN_EMAIL}"
: "${SMOKE_ADMIN_PASSWORD:?set SMOKE_ADMIN_PASSWORD}"

cp .env.example .env
cp backend/.env.example backend/.env

# docker-compose.yml injects DATABASE_URL from POSTGRES_PASSWORD, so a second
# copy of the password in backend/.env.example is precisely the bug that silently
# broke this deploy. Pin the intent here.
if grep -qE '^[[:space:]]*DATABASE_URL=' backend/.env.example; then
    echo "::error file=backend/.env.example::DATABASE_URL must stay commented out - docker-compose.yml injects it from POSTGRES_PASSWORD. Two copies of the password is how this deploy broke."
    exit 1
fi

# stdlib only: neither `cryptography` nor `openssl` is guaranteed on the runner.
# A Fernet key is just urlsafe-base64 of 32 random bytes.
POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
FILE_ENCRYPTION_KEY="$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"

# ./.env - both keys already exist in the example, so rewrite them in place
# rather than appending a second definition.
sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${POSTGRES_PASSWORD}|" .env
sed -i "s|^SITE_ADDRESS=.*|SITE_ADDRESS=:80|" .env

# A sed that matched nothing is silent, so assert the result. Otherwise compose
# fails much later with a far vaguer message.
grep -qE '^POSTGRES_PASSWORD=.{16,}$' .env
grep -qxF 'SITE_ADDRESS=:80' .env

# ./backend/.env - append. Compose's env_file parser is last-key-wins, so these
# override the placeholders from the example (verified against
# `docker compose config`). A step after `up` asserts that this really happened
# rather than trusting it.
{
    echo ""
    echo "# --- injected by CI (.github/scripts/synthesize-env.sh) ---"
    echo "JWT_SECRET=${JWT_SECRET}"
    echo "FILE_ENCRYPTION_KEY=${FILE_ENCRYPTION_KEY}"
    echo "ADMIN_EMAIL=${SMOKE_ADMIN_EMAIL}"
    echo "ADMIN_PASSWORD=${SMOKE_ADMIN_PASSWORD}"
} >> backend/.env

# Show the shape of the config without printing any value.
echo "--- ./.env keys ---"
grep -oE '^[A-Z_]+=' .env
echo "--- backend/.env keys ---"
grep -oE '^[A-Z_]+=' backend/.env
