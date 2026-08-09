"""Tests for app/seed.py — default catalogue, admin bootstrap, idempotency.

DB-backed, so they use the same `requires_db`/`client` pattern as tests/test_api.py.
Note that the `client` fixture has ALREADY run seed() once by the time a test body
starts (conftest creates the schema, then seeds), so these tests inspect the result
of that first run and then re-run seed() to prove it is safe to repeat.

Idempotency matters operationally: `python -m app.seed` is documented as "run after
migrations", the Docker entrypoint runs it on every container start, and a re-hash
of the admin password on each boot would silently invalidate a password the user had
changed in the meantime.
"""

from contextlib import contextmanager

from sqlalchemy import func, select

from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, requires_db


@contextmanager
def _session():
    """A session on the TEST engine.

    SessionLocal is imported here, not at module import time: conftest's `client`
    fixture monkeypatches `app.db.SessionLocal` onto the test engine, and a
    module-level `from app.db import SessionLocal` would have captured the original.
    """
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@requires_db
def test_default_visit_types_are_seeded():
    from app.models import VisitType
    from app.seed import DEFAULT_VISIT_TYPES

    expected = dict(DEFAULT_VISIT_TYPES)
    assert len(DEFAULT_VISIT_TYPES) == 10
    assert len(expected) == 10, "duplicate key in DEFAULT_VISIT_TYPES"

    with _session() as db:
        rows = db.scalars(select(VisitType)).all()

    assert len(rows) == 10
    assert {r.key for r in rows} == set(expected)
    # Labels too: the frontend renders these, so a typo'd label is a user-visible bug.
    assert {r.key: r.label for r in rows} == expected
    assert all(r.id is not None for r in rows)


@requires_db
def test_seed_creates_exactly_one_admin_user():
    from app.auth.security import verify_password
    from app.models import User

    with _session() as db:
        users = db.scalars(select(User)).all()

    assert len(users) == 1, "seed must not create anything beyond the bootstrap admin"
    admin = users[0]
    assert admin.email == ADMIN_EMAIL
    assert admin.is_admin is True
    assert admin.created_at is not None

    # Password is hashed, never stored in the clear.
    assert admin.password_hash != ADMIN_PASSWORD
    assert admin.password_hash.startswith("$2b$")
    assert verify_password(ADMIN_PASSWORD, admin.password_hash)
    assert not verify_password("wrong-password", admin.password_hash)


@requires_db
def test_seed_is_idempotent(capsys):
    """Re-running seed() must not duplicate rows and must NOT re-hash the password.

    bcrypt salts randomly, so `hash_password(same_password)` returns a different
    string every call — byte-identity of password_hash is therefore a strong proof
    that seed() took the "already exists; skipping" branch instead of rewriting the
    credential.
    """
    from app.models import User, VisitType
    from app.seed import seed

    with _session() as db:
        before_hash = db.scalar(select(User.password_hash).where(User.email == ADMIN_EMAIL))
        before_id = db.scalar(select(User.id).where(User.email == ADMIN_EMAIL))
        before_visit_type_ids = sorted(db.scalars(select(VisitType.id)).all())
    assert before_hash is not None

    capsys.readouterr()  # discard whatever the fixture's own seed() printed
    seed()
    seed()  # twice: the second run also proves the first left nothing half-done
    out = capsys.readouterr().out

    with _session() as db:
        assert db.scalar(select(func.count()).select_from(VisitType)) == 10
        # Same row ids, i.e. no delete-and-recreate churn (which would break the
        # documents.visit_type_id foreign keys pointing at them).
        assert sorted(db.scalars(select(VisitType.id)).all()) == before_visit_type_ids

        admins = db.scalars(select(User).where(User.email == ADMIN_EMAIL)).all()
        assert len(admins) == 1
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert admins[0].id == before_id
        after_hash = admins[0].password_hash

    assert after_hash == before_hash
    assert after_hash.encode("utf-8") == before_hash.encode("utf-8")  # byte-identical

    assert "Admin user already exists; skipping." in out
    assert "Created admin user" not in out


@requires_db
def test_seed_restores_a_missing_visit_type():
    """Idempotent means "converges", not just "no-ops": a deleted row comes back."""
    from app.models import VisitType
    from app.seed import seed

    with _session() as db:
        victim = db.scalar(select(VisitType).where(VisitType.key == "vaccination"))
        assert victim is not None
        victim_id = victim.id
        db.delete(victim)
        db.commit()
        assert db.scalar(select(func.count()).select_from(VisitType)) == 9

    seed()

    with _session() as db:
        assert db.scalar(select(func.count()).select_from(VisitType)) == 10
        restored = db.scalar(select(VisitType).where(VisitType.key == "vaccination"))
        assert restored is not None
        assert restored.label == "Vaccinazione"
        # Recreated, not resurrected: the new row gets a fresh id. Any document that
        # had referenced the old id would have blocked the delete (FK), so this is
        # only reachable on an empty archive.
        assert restored.id != victim_id
