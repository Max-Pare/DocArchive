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
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

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

    # The schema fixture below runs `DROP SCHEMA public CASCADE` on whatever this
    # points at. Pointing it at a dev database (a one-character edit away from the
    # test one) would destroy it silently, so require the name to say _test.
    database = make_url(TEST_DB_URL).database or ""
    if not database.endswith("_test"):
        pytest.fail(
            f"TEST_DATABASE_URL points at database {database!r}, which does not end "
            "in '_test'. These tests DROP the public schema; refusing to run against "
            "a database that may not be disposable.",
            pytrace=False,
        )

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
    from alembic.config import Config

    from alembic import command

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


def _truncate_all(engine) -> None:
    """Empty every mapped table, leaving the migrated schema itself alone.

    alembic_version is deliberately not in Base.metadata, so it survives and the
    session-scoped migration run is not repeated per test.
    """
    import app.models  # noqa: F401  - registers the mappers on Base.metadata
    from app.db import Base

    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    if not tables:
        return
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture()
def client(migrated_engine, monkeypatch):
    """A TestClient against the real engine, with the tables emptied beforehand.

    An earlier version wrapped each test in one outer transaction and bound every
    session to that single connection with join_transaction_mode="create_savepoint",
    so a lone rollback undid the test. That was faster, but its correctness depended
    on the savepoint NESTING order between sessions that know nothing about each
    other: get_db() closes its session in a finally, and closing a savepoint-joined
    session rolls that savepoint back - discarding whatever a separately-opened
    session (run_ocr_for_document(), seed()) had already committed into it. It held
    together by luck, and stopped holding under Starlette's newer request handling,
    where it silently ate the OCR write and surfaced as an unrelated-looking
    full-text-search failure.

    Truncating instead is a little slower and completely boring: sessions commit for
    real, exactly as they do in production, and no test can depend on another's
    leftovers. Cleaning happens on the way IN, so a failed test leaves its rows on
    the table for inspection.
    """
    from fastapi.testclient import TestClient

    # settings is a module-level singleton built at import time, so clearing the
    # lru_cache alone would not rebind it.
    from app.config import get_settings

    get_settings.cache_clear()
    import app.config as config_module

    config_module.settings = get_settings()

    import app.db as db_module

    # Read before the monkeypatch below replaces it, so teardown restores the app's
    # own engine rather than this session's test engine.
    original_bind = db_module.engine

    monkeypatch.setattr(db_module, "engine", migrated_engine)

    # Reconfigure the EXISTING sessionmaker in place rather than rebinding the name.
    # app/seed.py and app/ocr/service.py both do `from app.db import SessionLocal`,
    # which copies the reference at import time, so monkeypatching
    # app.db.SessionLocal leaves those two modules pointing at the original. That is
    # not theoretical: it made the first DB test pass (app.seed was imported after
    # the patch, so it captured the right object) and every subsequent one fail with
    # ResourceClosedError, because the cached module still held the previous test's
    # closed connection. configure() mutates the shared object, so all holders agree.
    db_module.SessionLocal.configure(bind=migrated_engine)

    _truncate_all(migrated_engine)

    # storage caches its Fernet in a module global; drop it so this session's key
    # is the one actually used.
    import app.storage as storage_module

    monkeypatch.setattr(storage_module, "_fernet", None)

    from app.main import app
    from app.seed import seed

    seed()

    with TestClient(app) as c:
        yield c

    # monkeypatch cannot undo configure(), so restore the shared sessionmaker by hand.
    db_module.SessionLocal.configure(bind=original_bind)


# Backwards-compatible marker used by tests/test_api.py. Requesting `client`
# pulls in `db_url`, so the skip/fail decision happens there.
requires_db = pytest.mark.usefixtures("client")
