# DocArchive runbook

The 2am document. Ordered by **urgency, not by logic** — the reader is usually
panicking. Commands are verbatim; prose is minimal.

Everything below assumes you are in the repo root and the stack is the default
project (`docarchive`).

---

## First-time setup

Do this once, before anything else. Roughly ten minutes.

```bash
# 1. Generate the backup keypair.
mkdir -p ~/.config/age && chmod 700 ~/.config/age
age-keygen -o ~/.config/age/docarchive.txt
chmod 600 ~/.config/age/docarchive.txt

# 2. The public key goes in the repo (it is not a secret).
cp ops/backup-recipient.txt.example ops/backup-recipient.txt
# ...then paste the "Public key: age1..." value into it and commit.

# 3. The private key goes in your password manager. Nowhere else.
cat ~/.config/age/docarchive.txt
```

Then **escrow the secrets**, which is the step everything else depends on:

| Secret | Where it must live | If lost |
|---|---|---|
| `FILE_ENCRYPTION_KEY` (`backend/.env`) | Password manager **and on paper** | **Every original document is unrecoverable.** Nothing can help you. |
| age private key | Password manager | You cannot open any backup. |
| `JWT_SECRET` | Password manager | Harmless — set a new one; everyone logs in again. |
| `POSTGRES_PASSWORD` (`.env`) | Password manager | Rotate it in `.env`; the compose file derives `DATABASE_URL` from it. |
| `ADMIN_PASSWORD` | Password manager | Only used at first-ever seed. |

Paper is not a joke for the Fernet key. It is 44 base64 characters, and it is
immune to disk failure, ransomware and account lockout. The other stakeholders
here are family members who would need the archive if you were unavailable.

**The asymmetry worth understanding:** if the Fernet key is lost, Postgres still
holds every document's metadata *and* the full cleartext `ocr_text`. The content
survives; the originals die. That surprises people.

---

## 1. The site is down

```bash
docker compose ps
```

| What you see | What it means | Do this |
|---|---|---|
| A service is `restarting` | Crash loop | `docker compose logs --tail 80 <svc>` |
| `backend` exited 126 | `entrypoint.sh` lost its exec bit | Rebuild: `docker compose build --no-cache backend`. The `check-shebang-scripts-are-executable` pre-commit hook exists to stop this recurring. |
| `backend` exits after "Running database migrations" | Migration failed | See §4 |
| Everything `running`, site still dead | Proxy or DNS | `docker compose logs proxy` |
| `no space left on device` | See §5 |

The backend's own health probe only proves the process answers. If it is healthy
but nothing works, check the database:

```bash
docker compose exec -T db pg_isready -U docarchive
```

---

## 2. Restore from backup

**Rehearse first if you possibly can.** This variant restores into a completely
separate set of Docker volumes, on a different port, and cannot touch the real
archive — you can run it while the real stack is up:

```bash
export COMPOSE_PROJECT_NAME=docarchive-verify
export COMPOSE_FILE=docker-compose.yml:ops/docker-compose.verify.yml

ops/restore.sh --yes-destroy-current-data /var/backups/docarchive/<stamp>.tar.age
API_BASE=http://localhost:18080 ops/verify-backup.sh

docker compose down -v          # tear the rehearsal down
unset COMPOSE_PROJECT_NAME COMPOSE_FILE
```

**`COMPOSE_FILE` is not optional.** Without it the rehearsal uses the real compose
file and fights the live stack for ports 80 and 443. The override also drops 443
entirely — a rehearsal has no business requesting a certificate. Set
`VERIFY_HTTP_PORT` if 18080 is taken.

The real thing:

```bash
ops/restore.sh --yes-destroy-current-data /var/backups/docarchive/<stamp>.tar.age
ops/verify-backup.sh
```

`restore.sh` refuses to run without `--yes-destroy-current-data`, uses
`docker compose down` and **never** `down -v`, and stops if the restored
`alembic_version` does not match the backup's manifest.

**If it warns that the checkout is older than the backup, stop.** Running newer
data under older code is the silent-corruption case. Check out the commit named
in `MANIFEST.txt` (`git_sha`) and restore again.

---

## 3. Upgrade

```bash
ops/deploy.sh
```

That is: backup → `git pull --ff-only` → build → `up -d --wait` → assert
`/api/health`, assert `alembic_version` matches the checkout, assert every
service has `RestartCount == 0`.

**Rolling back:**

```bash
git checkout <previous-sha>
docker compose up -d --build
```

…**but a migration that already ran is not undone by a git checkout.** If the
upgrade included one, the only way back is the dump taken immediately before it —
which is why step 1 of `deploy.sh` is a backup. Restore per §2.

---

## 4. A migration failed mid-upgrade

```bash
docker compose logs backend | tail -40
docker compose exec -T db psql -U docarchive -d docarchive -c 'select * from alembic_version'
cd backend && alembic heads
```

- **`alembic_version` matches a real revision** — the migration did not start, or
  fully rolled back. Fix the cause and redeploy.
- **`alembic_version` is a revision that is not in the repo** — you are running
  older code against a newer database. Check out the newer commit.
- **Anything else** — restore from the pre-upgrade backup (§2). Do not hand-edit
  `alembic_version` to make the error go away; that trades a loud failure for a
  silent one.

Migrations run from `entrypoint.sh` on every boot, so a fixed migration applies
on the next `docker compose up -d`.

---

## 5. The disk is full

```bash
df -h
docker system df
```

- Container logs are already capped at 10MB × 3 per service by the `x-logging`
  anchor in `docker-compose.yml`.
- Old backups: `ls -lh /var/backups/docarchive` (pruned after
  `RETENTION_DAYS`, default 14).
- Build cache is usually the culprit: `docker system prune -af` — safe, it does
  not touch named volumes.
- **Never** `docker volume prune` here. `docarchive_file_data` is the archive.

---

## 6. Backups: what runs, and how you know it ran

Nothing is scheduled while the archive lives on a workstation. To run one now:

```bash
ops/backup.sh
```

When this moves to a always-on host, install the units:

```bash
sudo cp ops/systemd/docarchive-*.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now docarchive-backup.timer docarchive-verify.timer
systemctl list-timers 'docarchive*'
journalctl -u docarchive-backup -n 50
```

Set `/etc/docarchive-backup.env`:

```
BACKUP_DIR=/var/backups/docarchive
RETENTION_DAYS=14
RCLONE_REMOTE=remote:docarchive-backups
HEALTHCHECK_PING_URL=https://hc-ping.com/<uuid>
```

**The ping is the important line.** A backup system that silently stopped four
months ago is indistinguishable from no backup system, and that is how these
actually fail — not with an error, with silence.

**Test the alert once.** Stop the timer for 25 hours and confirm you actually get
the email. An untested alert is not an alert.

---

## 7. Annual drill

Once a year, restore on a machine that has never seen this project, using **only**
what is in your password manager:

1. `git clone` the repo.
2. Fetch the newest backup from the offsite remote.
3. `AGE_IDENTITY=<path> ops/restore.sh --yes-destroy-current-data <file>`
4. `ops/verify-backup.sh`

If that works, the escrow is real. If it does not, you found out on a Tuesday
instead of during a disaster.

---

## Known limits

- **There is no key rotation.** `FILE_ENCRYPTION_KEY` is a single key with no
  `MultiFernet` fallback list, so changing it makes every existing document
  undecryptable. Tooling for this is planned; until it lands, treat the key as
  permanent.
- **Secrets are plaintext environment variables** read via `env_file:`, so
  `FILE_ENCRYPTION_KEY` is visible to anything that can run `docker inspect` or
  read `/proc/<pid>/environ`. A deliberate tradeoff for a single-operator
  archive — see `SECURITY.md`.
- **`ocr_text` is stored unencrypted in Postgres.** The database dump is as
  sensitive as the file volume. This is why `backup.sh` encrypts everything and
  will not run without a recipient key.
