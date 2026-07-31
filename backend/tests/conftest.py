"""Test fixtures.

Postgres is required for the DB-backed tests: full-text search is Postgres-specific.
Set TEST_DATABASE_URL, e.g.
  postgresql+psycopg2://docarchive:docarchive@localhost:5432/docarchive_test

Three distinct states, deliberately:
  * TEST_DATABASE_URL unset          -> DB tests skip (fine for a laptop)
  * set but unreachable             -> hard failure, never a silent skip
  * DOCARCHIVE_REQUIRE_DB=1 and unset -> hard failure (CI must not skip)

The previous version collapsed "not configured" and "typo'd/down" into the same
silent skip, so `pytest` exited 0 with every API test skipped and nobody noticed
that they had never once executed.
"""
import os
import tempfile

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# --------------------------------------------------------------------------
# Environment isolation. This block MUST run before anything imports `app.*`.
#
# app/config.py declares `env_file=".env"`, and pytest's rootdir is backend/, so
# the developer's real backend/.env was being loaded into test settings: its
# ADMIN_EMAIL/ADMIN_PASSWORD differ from the constants the tests assert on, and
# its STORAGE_DIR pointed somewhere unwritable. os.environ outranks the dotenv
# file in pydantic-settings' precedence order, so setting these here wins.
# --------------------------------------------------------------------------
TEST_DB_URL = os.getenv("TEST_DATABASE_URL")
REQUIRE_DB = os.getenv("DOCARCHIVE_REQUIRE_DB") == "1"

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "changeme"

TEST_STORAGE_DIR = tempfile.mkdtemp(prefix="docarchive-test-files-")
TEST_FERNET_KEY = Fernet.generate_key().decode()

os.environ.update(
    {
        "ENVIRONMENT": "development",
        "JWT_SECRET": "test-secret-not-used-in-production",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "720",
        "STORAGE_DIR": TEST_STORAGE_DIR,
        "FILE_ENCRYPTION_KEY": TEST_FERNET_KEY,
        "MAX_UPLOAD_BYTES": str(25 * 1024 * 1024),
        "OCR_LANGUAGES": "ita",
        "PDF_DPI": "200",
        "CORS_ORIGINS": "http://localhost:5173",
        "ADMIN_EMAIL": ADMIN_EMAIL,
        "ADMIN_PASSWORD": ADMIN_PASSWORD,
    }
)
if TEST_DB_URL:
    os.environ["DATABASE_URL"] = TEST_DB_URL


@pytest.fixture(scope="session")
def db_url() -> str:
    """Resolve the test DB, distinguishing 'unconfigured' from 'broken'."""
    if not TEST_DB_URL:
        if REQUIRE_DB:
            pytest.fail(
                "DOCARCHIVE_REQUIRE_DB=1 but TEST_DATABASE_URL is unset. "
                "CI must run the DB tests, not skip them.",
                pytrace=False,
            )
        pytest.skip("TEST_DATABASE_URL not configured; set it to run DB tests")

    engine = create_engine(TEST_DB_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.fail(
            f"TEST_DATABASE_URL is set but unreachable: {TEST_DB_URL!r}\n{exc!r}\n"
            "This is a hard failure on purpose - a typo or a stopped container "
            "must never look like 'no DB configured'.",
            pytrace=False,
        )
    finally:
        engine.dispose()
    return TEST_DB_URL


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """slowapi's storage is process-global and survives a new TestClient.

    Without this, the login limit (10/minute) leaks across tests and any
    expansion of the suite starts returning spurious 429s. Tests that want to
    assert on throttling re-enable the limiter themselves.
    """
    from app.rate_limit import limiter

    limiter.reset()
    limiter.enabled = False
    yield
    limiter.reset()
    limiter.enabled = True


@pytest.fixture()
def client(db_url, monkeypatch):
    from fastapi.testclient import TestClient

    # settings is a module-level singleton built at import time, so clearing the
    # lru_cache alone would not rebind it.
    from app.config import get_settings

    get_settings.cache_clear()
    import app.config as config_module

    config_module.settings = get_settings()

    # `import app.models` is load-bearing: Base.metadata is populated as a side
    # effect of importing the model modules, and create_all() below silently
    # creates NOTHING if they have not been imported yet. Until now this worked
    # only by accident - tests/test_api.py has an autouse fixture that patches
    # app.ocr.service, which happens to import app.models first. A DB test module
    # that does not drag app.models in got an empty schema, and the CREATE INDEX
    # below then failed with 'relation "documents" does not exist'.
    import app.db as db_module
    import app.models
    from app.db import Base

    engine = create_engine(db_url)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=engine, autoflush=False, autocommit=False),
    )

    # storage caches its Fernet in a module global; drop it so this session's key
    # is the one actually used.
    import app.storage as storage_module

    monkeypatch.setattr(storage_module, "_fernet", None)

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    # The FTS index is raw SQL in the migration and therefore absent from
    # Base.metadata. Wave 2 replaces create_all() with `alembic upgrade head`,
    # which removes this duplication.
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_documents_fts ON documents USING GIN "
                "(to_tsvector('italian', coalesce(ocr_text, '') || ' ' || original_filename))"
            )
        )

    from app.main import app
    from app.seed import seed

    seed()

    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(engine)
    engine.dispose()


# Backwards-compatible marker used by tests/test_api.py. Requesting `client`
# pulls in `db_url`, so the skip/fail decision happens there.
requires_db = pytest.mark.usefixtures("client")
