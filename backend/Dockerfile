FROM python:3.12-slim

# OCR + PDF rasterization system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-ita \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The exec bit must be set inside the build: a ZIP download, an NTFS checkout, or
# any copy without -p loses it, and CMD ["./entrypoint.sh"] then fails with exit 126.
RUN chmod +x ./entrypoint.sh

# Non-root user; storage dir is a mounted volume owned to this user at runtime.
RUN useradd -m appuser && mkdir -p /data/files && chown -R appuser:appuser /data
USER appuser

EXPOSE 8000

# entrypoint runs migrations + seed, then serves
CMD ["./entrypoint.sh"]
