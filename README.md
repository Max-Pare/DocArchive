# DocArchive

Personal/family medical-document archive. Upload scans (PDF/image), OCR extracts
the text (Tesseract, Italian), and you find documents fast by **visit type + date +
tags + full-text search**. Per-user private data, JWT auth, files encrypted at rest.

- **Backend:** FastAPI + SQLAlchemy + Postgres, Tesseract OCR (native).
- **Frontend:** React + TypeScript (Vite), React Query.
- **Deploy:** Docker Compose (Postgres, backend, frontend, Caddy reverse proxy w/ auto-HTTPS).

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

   Also set `DATABASE_URL` password to match `POSTGRES_PASSWORD`, and `CORS_ORIGINS`
   to your public URL (e.g. `https://docarchive.example.com`). Change `ADMIN_EMAIL`
   / `ADMIN_PASSWORD` — the first admin is created from these on first boot.

2. **Launch**

   ```bash
   docker compose up -d --build
   ```

   On startup the backend runs Alembic migrations and seeds visit types + the admin
   user automatically. App is served at `SITE_ADDRESS`.

3. **Log in** with `ADMIN_EMAIL` / `ADMIN_PASSWORD`, then go to **Utenti** to create
   family accounts.

---

## Local development (no Docker for the app)

Backend:

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# needs local tesseract + tesseract-ita + poppler installed on PATH
cp .env.example .env    # set FILE_ENCRYPTION_KEY, point DATABASE_URL at your Postgres
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api -> http://localhost:8000
```

---

## Testing

Pure OCR-suggestion logic (no DB, no tesseract):

```bash
cd backend && pytest tests/test_suggest.py
```

Full API tests (auth, owner isolation, upload/download, search) need a Postgres test DB:

```bash
export TEST_DATABASE_URL="postgresql+psycopg2://docarchive:docarchive@localhost:5432/docarchive_test"
pytest                       # DB-backed tests auto-skip if the URL is unreachable
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

## Backups (VPS)

- Database: `docker compose exec db pg_dump -U docarchive docarchive > backup.sql`
- Files: back up the `file_data` volume (`/var/lib/docker/volumes/...`) **and** keep
  `FILE_ENCRYPTION_KEY` somewhere safe — without it the encrypted files are useless.

## Security notes

- HTTPS via Caddy (set `SITE_ADDRESS` to a real domain for auto-TLS).
- Passwords bcrypt-hashed; JWT signed with `JWT_SECRET`; login rate-limited (10/min/IP).
- Files Fernet-encrypted at rest; all document routes owner-scoped server-side.
- CORS locked to `CORS_ORIGINS`; upload size + MIME type validated.
- Never commit `.env` / `backend/.env`.
