"""DB-backed test fixtures.

Requires a Postgres test database (full-text search is Postgres-specific).
Set TEST_DATABASE_URL, e.g.:
  postgresql+psycopg2://docarchive:docarchive@localhost:5432/docarchive_test

Tests that need the DB are skipped automatically if it is unreachable.
"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TEST_DB_URL = os.getenv("TEST_DATABASE_URL")


def _db_available() -> bool:
    if not TEST_DB_URL:
        return False
    try:
        eng = create_engine(TEST_DB_URL)
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not _db_available(), reason="TEST_DATABASE_URL not reachable")


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from cryptography.fernet import Fernet

    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    monkeypatch.setenv("FILE_ENCRYPTION_KEY", Fernet.generate_key().decode())

    # import after env is set so settings pick them up
    from app.config import get_settings
    get_settings.cache_clear()

    import app.db as db_module
    from app.db import Base

    engine = create_engine(TEST_DB_URL)
    db_module.engine = engine
    db_module.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    # FTS index is raw SQL in the migration; recreate it here for search tests.
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_documents_fts ON documents USING GIN "
            "(to_tsvector('italian', coalesce(ocr_text, '') || ' ' || original_filename))"
        ))

    from app.main import app
    from app.seed import seed
    seed()

    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(engine)
