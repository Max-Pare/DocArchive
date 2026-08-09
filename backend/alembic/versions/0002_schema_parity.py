"""align the database with the ORM models

The ORM and 0001 had drifted in two ways, both found by comparing
Base.metadata against a freshly migrated database (5 items total):

1. Three timestamp columns are declared non-Optional in the models -- i.e. NOT NULL
   -- but 0001 created them nullable: users.created_at, documents.created_at and
   documents.updated_at. Because the test suite built its schema with
   create_all(), tests ran against NOT NULL columns while production ran against
   nullable ones, so nothing ever caught it.

2. users.email and visit_types.key each got BOTH a column-level `unique=True`
   (which makes Postgres auto-create users_email_key / visit_types_key_key) AND an
   explicit unique index (ix_users_email / ix_visit_types_key). Uniqueness was
   therefore enforced twice, with two indexes maintained on every write. The ORM
   only declares the indexed form, so the auto-created constraints are dropped here.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-31
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# (table, column) triples that must become NOT NULL.
_TIMESTAMP_COLUMNS = [
    ("users", "created_at"),
    ("documents", "created_at"),
    ("documents", "updated_at"),
]


def upgrade() -> None:
    # Backfill before tightening. The column has had a server_default of now() all
    # along, so a NULL can only exist if a row was inserted with an explicit NULL --
    # unlikely, but ALTER ... SET NOT NULL fails hard on even one, and this migration
    # must be safe against a deployment whose contents we cannot inspect.
    for table, column in _TIMESTAMP_COLUMNS:
        op.execute(f"UPDATE {table} SET {column} = now() WHERE {column} IS NULL")  # noqa: S608
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            existing_server_default=sa.text("now()"),
            nullable=False,
        )

    # Redundant with the unique indexes created in 0001.
    op.drop_constraint("users_email_key", "users", type_="unique")
    op.drop_constraint("visit_types_key_key", "visit_types", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("visit_types_key_key", "visit_types", ["key"])
    op.create_unique_constraint("users_email_key", "users", ["email"])

    for table, column in _TIMESTAMP_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            existing_server_default=sa.text("now()"),
            nullable=True,
        )
