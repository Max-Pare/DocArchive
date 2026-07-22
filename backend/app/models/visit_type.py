from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class VisitType(Base):
    __tablename__ = "visit_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    # machine key used for keyword matching in OCR suggestions
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
