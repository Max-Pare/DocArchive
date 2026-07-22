import io
from datetime import date

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
)
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload

from app.auth.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models import Document, Tag, User, VisitType
from app.ocr.service import run_ocr_for_document
from app.ocr.suggest import guess_date, guess_visit_type_key, suggest_tags
from app.schemas.document import DocumentOut, DocumentUpdate, OcrSuggestion
from app.storage import delete_file, read_decrypted, save_encrypted

router = APIRouter(prefix="/documents", tags=["documents"])


def _get_owned(db: Session, doc_id: int, user: User) -> Document:
    doc = db.scalar(
        select(Document)
        .where(Document.id == doc_id, Document.owner_id == user.id)
        .options(selectinload(Document.tags), selectinload(Document.visit_type))
    )
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return doc


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if file.content_type not in settings.allowed_mime_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {file.content_type}",
        )
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.max_upload_bytes} bytes",
        )

    stored_path, size = save_encrypted(data, current.id)
    doc = Document(
        owner_id=current.id,
        original_filename=file.filename or "upload",
        stored_path=stored_path,
        mime_type=file.content_type,
        file_size=size,
        status="uploaded",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # OCR always runs (text is indexed regardless of Auto-fill button).
    background.add_task(run_ocr_for_document, doc.id)
    return _get_owned(db, doc.id, current)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    q: str | None = Query(default=None, description="Full-text query over OCR text + filename"),
    visit_type_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    tag_ids: list[int] | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Document)
        .where(Document.owner_id == current.id)
        .options(selectinload(Document.tags), selectinload(Document.visit_type))
    )
    if visit_type_id is not None:
        stmt = stmt.where(Document.visit_type_id == visit_type_id)
    if date_from is not None:
        stmt = stmt.where(Document.doc_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Document.doc_date <= date_to)
    if tag_ids:
        # match documents having ALL requested tags
        stmt = (
            stmt.join(Document.tags)
            .where(Tag.id.in_(tag_ids))
            .group_by(Document.id)
            .having(func.count(func.distinct(Tag.id)) == len(set(tag_ids)))
        )
    if q:
        # Postgres full-text over ocr_text + filename; italian config.
        ts = func.to_tsvector(
            "italian",
            func.coalesce(Document.ocr_text, "") + " " + Document.original_filename,
        )
        stmt = stmt.where(ts.op("@@")(func.plainto_tsquery("italian", q)))

    stmt = stmt.order_by(Document.doc_date.desc().nullslast(), Document.created_at.desc())
    stmt = stmt.limit(limit).offset(offset)
    return db.scalars(stmt).unique().all()


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _get_owned(db, doc_id, current)


@router.patch("/{doc_id}", response_model=DocumentOut)
def update_document(
    doc_id: int,
    payload: DocumentUpdate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = _get_owned(db, doc_id, current)
    data = payload.model_dump(exclude_unset=True)

    if "visit_type_id" in data and data["visit_type_id"] is not None:
        if db.get(VisitType, data["visit_type_id"]) is None:
            raise HTTPException(status_code=400, detail="Unknown visit_type_id")
    for field in ("doc_date", "visit_type_id", "title", "notes"):
        if field in data:
            setattr(doc, field, data[field])

    if "tag_ids" in data and data["tag_ids"] is not None:
        tags = db.scalars(
            select(Tag).where(Tag.id.in_(data["tag_ids"]), Tag.owner_id == current.id)
        ).all()
        doc.tags = list(tags)

    db.commit()
    return _get_owned(db, doc_id, current)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(doc_id: int, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = _get_owned(db, doc_id, current)
    delete_file(doc.stored_path)
    db.delete(doc)
    db.commit()


@router.get("/{doc_id}/file")
def download_file(doc_id: int, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = _get_owned(db, doc_id, current)
    data = read_decrypted(doc.stored_path)
    return StreamingResponse(
        io.BytesIO(data),
        media_type=doc.mime_type,
        headers={"Content-Disposition": f'inline; filename="{doc.original_filename}"'},
    )


@router.post("/{doc_id}/ocr", response_model=OcrSuggestion)
def run_ocr_and_suggest(
    doc_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """(Re)run OCR synchronously and return field suggestions for the Auto-fill button."""
    doc = _get_owned(db, doc_id, current)
    run_ocr_for_document(doc.id)
    db.refresh(doc)

    text = doc.ocr_text or ""
    vt_key = guess_visit_type_key(text)
    vt = db.scalar(select(VisitType).where(VisitType.key == vt_key)) if vt_key else None
    return OcrSuggestion(
        doc_date=guess_date(text),
        visit_type_id=vt.id if vt else None,
        visit_type_key=vt.key if vt else None,
        suggested_tags=suggest_tags(text),
        ocr_text_excerpt=(text[:500] or None),
        status=doc.status,
    )
