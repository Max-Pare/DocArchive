# DocArchive

Personal/family medical-document archive. Upload scans (PDF/image), OCR extracts
the text (Tesseract, Italian), and you find documents fast by **visit type + date +
tags + full-text search**. Per-user private data, JWT auth, files encrypted at rest.

- **Backend:** FastAPI + SQLAlchemy + Postgres, Tesseract OCR (native).
- **Frontend:** React + TypeScript (Vite), React Query.
- **Deploy:** Docker Compose (Postgres, backend, frontend, Caddy reverse proxy w/ auto-HTTPS).

## SLOP WARNING

This application was entirely vibe coded, deploy at your own risk.

## Architecture

```
[React SPA] --/--> [Caddy] --/api--> [FastAPI] --> [Postgres]   (metadata, OCR text, users)
                                          |
                                          +--> [encrypted files on disk]
                                          +--> [Tesseract + poppler]  (OCR)
```

Documents are owner-scoped (`owner_id`); every read filters to the logged-in user.
Files are Fernet-encrypted before hitting disk. OCR runs as a background task on
upload and can be re-run on demand via **Compila automaticamente** (Auto-fill), which
suggests date / visit type / tags — always editable, never auto-committed.

---

## Quick start (Docker, production-ish)

1. **Create secrets**

   ```bash
   cp .env.example .env                     # set POSTGRES_PASSWORD, SITE_ADDRESS
   cp backend/.env.example backend/.env
   ```

   Generate the two required backend secrets and paste them into `backend/.env`:

   ```bash
   # JWT_SECRET
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   # FILE_ENCRYPTION_KEY  (KEEP THIS SAFE — losing it makes files unreadable)
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   Leave `DATABASE_URL` commented out: under Compose it is built from
   `POSTGRES_PASSWORD` in `./.env` and injected into the container, so a second copy
   in `backend/.env` can only drift out of sync. Set `CORS_ORIGINS` to your public URL
   (e.g. `https://docarchive.example.com`), and change `ADMIN_EMAIL` / `ADMIN_PASSWORD`
   — the first admin is created from these on first boot.

2. **Back up `FILE_ENCRYPTION_KEY` before you upload anything.**

   Put it in a password manager, and write it down on paper. It is 44 characters
   and it is the only thing standing between you and permanent, total loss of every
   original document. There is no recovery, no escrow and no rotation.

   The asymmetry surprises people: if the key is lost, Postgres still holds every
   document's metadata *and* its full OCR'd text. The content survives — the
   originals do not.

3. **Launch**

   ```bash
   docker compose up -d --build
   ```

   On startup the backend runs Alembic migrations and seeds visit types + the admin
   user automatically. App is served at `SITE_ADDRESS`.

4. **Log in** with `ADMIN_EMAIL` / `ADMIN_PASSWORD`, then go to **Utenti** to create
   family accounts.

---

## Local development (no Docker for the app)

Backend:

```bash
cd backend
# Python 3.12 to match the runtime image; `uv` will fetch it if you don't have it.
uv venv --python 3.12 .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
uv pip install -r requirements-dev.txt                   # includes pytest + httpx
# needs local tesseract + tesseract-ita + poppler installed on PATH
cp .env.example .env    # set FILE_ENCRYPTION_KEY, and DATABASE_URL for non-Docker use
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm ci             # `ci` not `install`: the lockfile is the pinned source of truth
npm run dev        # http://localhost:5173, proxies /api -> http://localhost:8000
```

---

## Testing

Unit tests that need neither Postgres nor tesseract run with no setup:

```bash
cd backend && pytest
```

The DB-backed tests (auth, owner isolation, upload/download, full-text search) need a
Postgres test database — full-text search is Postgres-specific, so it cannot be faked:

```bash
createdb docarchive_test        # or: psql -c 'CREATE DATABASE docarchive_test'
export TEST_DATABASE_URL="postgresql+psycopg2://docarchive:<password>@localhost:5432/docarchive_test"
pytest
```

The database name **must end in `_test`** — the fixtures rebuild the schema with
`DROP SCHEMA public CASCADE`, so pointing this at a dev database would wipe it. A name
that does not match is a hard failure, not a warning. The migration tests additionally
`CREATE DATABASE` / `DROP DATABASE`, so the role needs `CREATEDB`.

`TEST_DATABASE_URL` has three deliberately distinct behaviours:

| State | Result |
|---|---|
| unset | DB tests skip (convenient on a laptop) |
| set but unreachable | **hard failure** — a typo or a stopped container must never look like "no DB configured" |
| `DOCARCHIVE_REQUIRE_DB=1` and unset | **hard failure** — CI must run these tests, never skip them |

That distinction matters: the DB-backed tests previously collapsed all three into a silent
skip, so `pytest` exited 0 while they had in fact never once executed.

Note the compose `db` service publishes no ports. To run the tests against it, either
point `TEST_DATABASE_URL` at the container IP
(`docker inspect docarchive-db-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'`)
or run your own local Postgres.

Frontend:

```bash
cd frontend && npm test        # vitest
npm run typecheck              # tsc --noEmit
```

## Manual end-to-end check

1. Admin creates a user → log in as that user.
2. **Carica** an Italian blood-test PDF → redirected to the document page.
3. Click **✨ Compila automaticamente** → verify date, visit type, tags are suggested.
4. Edit if needed → **Salva**.
5. Back in **Archivio**, filter by visit type + date range, and search a word that
   appears in the scan → the document shows up.
6. Log in as a different user → confirm the document is **not** visible (isolation).
7. Open the document → the preview renders the original; download matches the upload.

## Backups, restore, upgrades

See **[ops/RUNBOOK.md](ops/RUNBOOK.md)**. Short version:

```bash
ops/backup.sh      # one encrypted, checksummed, self-describing archive
ops/restore.sh --yes-destroy-current-data <file>
ops/verify-backup.sh   # proves the restored documents actually decrypt
ops/deploy.sh      # backup, pull, build, up, then assert it really came up
```

A backup contains the database dump, both volumes, the `.env` files, and a manifest
recording the commit, the Alembic revision and the image digests. It is encrypted to
an age public key, so the backup job holds no secret; only restore needs the private
key. That is not optional: `documents.ocr_text` is stored in Postgres in **cleartext**,
so the dump contains the full text of every document and is exactly as sensitive as
the encrypted files.

## Security notes

- HTTPS via Caddy (set `SITE_ADDRESS` to a real domain for auto-TLS).
- Passwords bcrypt-hashed; JWT signed with `JWT_SECRET`; login rate-limited (10/min/IP).
- Files Fernet-encrypted at rest; all document routes owner-scoped server-side.
- CORS locked to `CORS_ORIGINS`; upload size + MIME type validated.
- Never commit `.env` / `backend/.env`.
