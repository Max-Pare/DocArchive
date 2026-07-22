"""OCR pipeline: turn a document's bytes into plain text.

Strategy:
  - PDF with an embedded text layer  -> extract text directly (pypdf), fast + exact.
  - PDF without usable text          -> rasterize pages (pdf2image/poppler) -> tesseract.
  - Image                            -> tesseract directly (Pillow).
"""
import io

from app.config import settings

_MIN_PDF_TEXT_CHARS = 40  # below this we assume the PDF is a scan and OCR it


def _ocr_image_bytes(data: bytes) -> str:
    import pytesseract
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    return pytesseract.image_to_string(img, lang=settings.ocr_languages)


def _pdf_embedded_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    return "\n".join(parts).strip()


def _ocr_pdf_scanned(data: bytes) -> str:
    import pytesseract
    from pdf2image import convert_from_bytes

    images = convert_from_bytes(data, dpi=settings.pdf_dpi)
    parts = [pytesseract.image_to_string(img, lang=settings.ocr_languages) for img in images]
    return "\n".join(parts).strip()


def extract_text(data: bytes, mime_type: str) -> str:
    """Best-effort text extraction. Raises on hard failure (caller marks ocr_failed)."""
    if mime_type == "application/pdf":
        embedded = _pdf_embedded_text(data)
        if len(embedded) >= _MIN_PDF_TEXT_CHARS:
            return embedded
        return _ocr_pdf_scanned(data)
    if mime_type.startswith("image/"):
        return _ocr_image_bytes(data)
    raise ValueError(f"Unsupported mime type for OCR: {mime_type}")
