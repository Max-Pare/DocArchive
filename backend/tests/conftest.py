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
import pathlib
import tempfile

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent

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


def _run_alembic_upgrade(url: str) -> None:
    """Build the schema the way production does: by running the migrations."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    # Absolute, so this works regardless of the cwd pytest was invoked from.
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def migrated_engine(db_url):
    """Session-scoped engine whose schema was built by `alembic upgrade head`.

    Previously each test did drop_all()/create_all() and then re-created the
    full-text index from a SQL string hand-copied out of 0001. That had two costs:
    the migrations were never executed by any test, so the models and the migration
    silently drifted apart (they had, in five places), and the FTS DDL existed in two
    places that could disagree.
    """
    engine = create_engine(db_url)
    with engine.begin() as conn:
        # Cheaper and more thorough than drop_all: also removes anything a previous
        # run's migrations created that Base.metadata does not know about.
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    _run_alembic_upgrade(db_url)
    yield engine
    engine.dispose()


@pytest.fixture()
def client(migrated_engine, monkeypatch):
    """A TestClient whose writes are all rolled back at the end of the test.

    Every test runs inside one outer transaction on a single connection. Sessions are
    bound to that connection with join_transaction_mode="create_savepoint", so code
    that opens its OWN session -- seed() and run_ocr_for_document() both do -- joins
    this transaction instead of committing independently. Their .commit() calls
    release a savepoint rather than writing for real, so a single rollback at the end
    undoes everything and the next test starts from the migrated, empty schema.
    """
    from fastapi.testclient import TestClient

    # settings is a module-level singleton built at import time, so clearing the
    # lru_cache alone would not rebind it.
    from app.config import get_settings

    get_settings.cache_clear()
    import app.config as config_module

    config_module.settings = get_settings()

    import app.db as db_module

    connection = migrated_engine.connect()
    outer = connection.begin()

    monkeypatch.setattr(db_module, "engine", migrated_engine)

    # Reconfigure the EXISTING sessionmaker in place rather than rebinding the name.
    # app/seed.py and app/ocr/service.py both do `from app.db import SessionLocal`,
    # which copies the reference at import time, so monkeypatching
    # app.db.SessionLocal leaves those two modules pointing at the original. That is
    # not theoretical: it made the first DB test pass (app.seed was imported after
    # the patch, so it captured the right object) and every subsequent one fail with
    # ResourceClosedError, because the cached module still held the previous test's
    # closed connection. configure() mutates the shared object, so all holders agree.
    original_bind = db_module.engine
    db_module.SessionLocal.configure(
        bind=connection,
        join_transaction_mode="create_savepoint",
    )

    # storage caches its Fernet in a module global; drop it so this session's key
    # is the one actually used.
    import app.storage as storage_module

    monkeypatch.setattr(storage_module, "_fernet", None)

    from app.main import app
    from app.seed import seed

    seed()

    with TestClient(app) as c:
        yield c

    outer.rollback()
    connection.close()
    # monkeypatch cannot undo configure(), so restore the shared sessionmaker by hand.
    db_module.SessionLocal.configure(
        bind=original_bind,
        join_transaction_mode="conditional_savepoint",
    )


# Backwards-compatible marker used by tests/test_api.py. Requesting `client`
# pulls in `db_url`, so the skip/fail decision happens there.
requires_db = pytest.mark.usefixtures("client")
