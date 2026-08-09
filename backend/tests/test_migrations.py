"""Tests for the migration chain itself.

These run against their own throwaway database so they cannot disturb the schema the
rest of the suite shares -- they drop and rebuild everything.

Why this file exists: the suite used to build its schema with
Base.metadata.create_all(), so the migrations were never executed by any test and the
models drifted away from them in five places without anything failing.
"""
import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from alembic import command
from tests.conftest import BACKEND_DIR

MIGRATION_TEST_DB = "docarchive_migrations_test"


def _config() -> Config:
    """Alembic config with no URL: migrations are driven through a live connection.

    Passing the URL as a string would mean round-tripping it through str(URL), which
    renders the password as '***' in SQLAlchemy 2.0, and through ConfigParser, which
    treats '%' as interpolation. Handing env.py a connection via attributes sidesteps
    both.
    """
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def _run(engine, direction: str, revision: str) -> None:
    cfg = _config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        getattr(command, direction)(cfg, revision)


def _head() -> str:
    return ScriptDirectory.from_config(_config()).get_current_head()


@pytest.fixture()
def scratch_engine(db_url):
    """An engine on a freshly created, empty database, dropped again afterwards."""
    admin_url = make_url(db_url).set(database="postgres")

    def _admin(sql: str) -> None:
        engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            with engine.connect() as conn:
                conn.execute(text(sql))
        finally:
            engine.dispose()

    _admin(f'DROP DATABASE IF EXISTS "{MIGRATION_TEST_DB}" WITH (FORCE)')
    _admin(f'CREATE DATABASE "{MIGRATION_TEST_DB}"')

    engine = create_engine(make_url(db_url).set(database=MIGRATION_TEST_DB))
    yield engine
    engine.dispose()
    _admin(f'DROP DATABASE IF EXISTS "{MIGRATION_TEST_DB}" WITH (FORCE)')


def test_single_head():
    """A branched migration chain makes `alembic upgrade head` ambiguous."""
    heads = ScriptDirectory.from_config(_config()).get_heads()
    assert len(heads) == 1, f"expected exactly one head, found {heads}"


def test_upgrade_applies_every_revision(scratch_engine):
    _run(scratch_engine, "upgrade", "head")

    tables = set(inspect(scratch_engine).get_table_names())
    assert {"users", "visit_types", "tags", "documents", "document_tag"} <= tables

    with scratch_engine.connect() as conn:
        stamped = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert stamped == _head()


def test_full_text_index_exists(scratch_engine):
    """The FTS index is raw SQL, so only running the migration proves it is created."""
    _run(scratch_engine, "upgrade", "head")

    with scratch_engine.connect() as conn:
        indexes = (
            conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'documents'")
            )
            .scalars()
            .all()
        )
    assert "ix_documents_fts" in indexes


def test_timestamps_are_not_null(scratch_engine):
    """Revision 0002 tightened these; assert the end state directly."""
    _run(scratch_engine, "upgrade", "head")

    inspector = inspect(scratch_engine)
    for table, column in [
        ("users", "created_at"),
        ("documents", "created_at"),
        ("documents", "updated_at"),
    ]:
        col = next(c for c in inspector.get_columns(table) if c["name"] == column)
        assert col["nullable"] is False, f"{table}.{column} should be NOT NULL"


def test_redundant_unique_constraints_are_gone(scratch_engine):
    """0001 enforced uniqueness twice; 0002 keeps only the indexed form."""
    _run(scratch_engine, "upgrade", "head")

    inspector = inspect(scratch_engine)
    for table, column, dropped in [
        ("users", "email", "users_email_key"),
        ("visit_types", "key", "visit_types_key_key"),
    ]:
        names = {c["name"] for c in inspector.get_unique_constraints(table)}
        assert dropped not in names
        # ...but uniqueness must still be enforced, by the unique index.
        unique_indexes = [
            ix
            for ix in inspector.get_indexes(table)
            if ix["unique"] and ix["column_names"] == [column]
        ]
        assert unique_indexes, f"{table}.{column} lost its uniqueness guarantee"


def test_downgrade_then_upgrade_round_trips(scratch_engine):
    """downgrade() was dead code until now; a broken one is only found by running it."""
    _run(scratch_engine, "upgrade", "head")
    _run(scratch_engine, "downgrade", "base")

    remaining = set(inspect(scratch_engine).get_table_names()) - {"alembic_version"}
    assert remaining == set(), f"downgrade left tables behind: {remaining}"

    _run(scratch_engine, "upgrade", "head")
    assert {"users", "documents"} <= set(inspect(scratch_engine).get_table_names())


def test_schema_matches_the_orm_models(scratch_engine):
    """The guard against model/migration drift.

    This failed with five entries before revision 0002: three NOT NULL mismatches on
    timestamp columns, plus two redundant unique constraints that Postgres auto-created
    from column-level unique=True alongside the explicit unique indexes.
    """
    import app.models  # noqa: F401  (populates Base.metadata as an import side effect)
    from app.db import Base
    from app.schema_filters import include_object

    _run(scratch_engine, "upgrade", "head")

    with scratch_engine.connect() as conn:
        context = MigrationContext.configure(
            conn,
            opts={"include_object": include_object, "compare_type": True},
        )
        diffs = compare_metadata(context, Base.metadata)

    assert diffs == [], (
        "database schema and ORM models have drifted; "
        f"`alembic revision --autogenerate` would emit: {diffs}"
    )
