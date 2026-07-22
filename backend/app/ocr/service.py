"""Run OCR for a document id in its own DB session (safe for BackgroundTasks)."""
import logging

from app.db import SessionLocal
from app.models import Document
from app.ocr.pipeline import extract_text
from app.storage import read_decrypted

logger = logging.getLogger(__name__)


def run_ocr_for_document(document_id: int) -> None:
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            return
        doc.status = "ocr_running"
        db.commit()

        try:
            data = read_decrypted(doc.stored_path)
            text = extract_text(data, doc.mime_type)
            doc.ocr_text = text
            doc.status = "ocr_done"
        except Exception:  # noqa: BLE001
            logger.exception("OCR failed for document %s", document_id)
            doc.status = "ocr_failed"
        db.commit()
    finally:
        db.close()
