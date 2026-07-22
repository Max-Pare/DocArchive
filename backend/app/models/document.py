from datetime import datetime, date

from sqlalchemy import (
    String, Text, Integer, BigInteger, Date, DateTime, ForeignKey, Table, Column, func, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# OCR/status values: uploaded | ocr_running | ocr_done | ocr_failed

document_tag = Table(
    "document_tag",
    Base.metadata,
    Column("document_id", ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # medical event date (nullable — may be unknown / filled later)
    doc_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    visit_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("visit_types.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship(back_populates="documents")  # noqa: F821
    visit_type: Mapped["VisitType | None"] = relationship()  # noqa: F821
    tags: Mapped[list["Tag"]] = relationship(secondary=document_tag)  # noqa: F821


# Full-text search index is created in the Alembic migration (GIN over tsvector).
Index("ix_documents_owner_date", Document.owner_id, Document.doc_date)
