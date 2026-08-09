"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-22
"""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_admin", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "visit_types",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.String(128), nullable=False),
    )
    op.create_index("ix_visit_types_key", "visit_types", ["key"], unique=True)

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "owner_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.UniqueConstraint("owner_id", "name", name="uq_tag_owner_name"),
    )
    op.create_index("ix_tags_owner_id", "tags", ["owner_id"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "owner_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("stored_path", sa.String(1024), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("file_size", sa.BigInteger, nullable=False),
        sa.Column("doc_date", sa.Date, nullable=True),
        sa.Column(
            "visit_type_id",
            sa.Integer,
            sa.ForeignKey("visit_types.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="uploaded"),
        sa.Column("ocr_text", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_documents_owner_id", "documents", ["owner_id"])
    op.create_index("ix_documents_doc_date", "documents", ["doc_date"])
    op.create_index("ix_documents_visit_type_id", "documents", ["visit_type_id"])
    op.create_index("ix_documents_owner_date", "documents", ["owner_id", "doc_date"])

    op.create_table(
        "document_tag",
        sa.Column(
            "document_id",
            sa.Integer,
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id", sa.Integer, sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
        ),
    )

    # Full-text search GIN index over ocr_text + filename (Italian config).
    op.execute(
        """
        CREATE INDEX ix_documents_fts ON documents
        USING GIN (
            to_tsvector('italian', coalesce(ocr_text, '') || ' ' || original_filename)
        )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_documents_fts", table_name="documents")
    op.drop_table("document_tag")
    op.drop_index("ix_documents_owner_date", table_name="documents")
    op.drop_index("ix_documents_visit_type_id", table_name="documents")
    op.drop_index("ix_documents_doc_date", table_name="documents")
    op.drop_index("ix_documents_owner_id", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_tags_owner_id", table_name="tags")
    op.drop_table("tags")
    op.drop_index("ix_visit_types_key", table_name="visit_types")
    op.drop_table("visit_types")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
