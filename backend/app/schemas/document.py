from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.catalog import TagOut, VisitTypeOut


class DocumentOut(BaseModel):
    id: int
    original_filename: str
    mime_type: str
    file_size: int
    doc_date: date | None
    visit_type: VisitTypeOut | None
    title: str | None
    notes: str | None
    status: str
    tags: list[TagOut]
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class DocumentUpdate(BaseModel):
    doc_date: date | None = None
    visit_type_id: int | None = None
    title: str | None = Field(default=None, max_length=512)
    notes: str | None = None
    tag_ids: list[int] | None = None  # full replacement set when provided


class OcrSuggestion(BaseModel):
    doc_date: date | None = None
    visit_type_id: int | None = None
    visit_type_key: str | None = None
    suggested_tags: list[str] = []
    ocr_text_excerpt: str | None = None
    status: str
