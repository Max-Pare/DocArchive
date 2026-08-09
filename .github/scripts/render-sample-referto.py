"""Render a fake Italian lab report as a PNG, for CI to OCR.

Run INSIDE the backend container, not on the runner. That is the point: it proves
the shipped image's own Pillow, fonts and tesseract-ita are present, rather than
whatever apt put on the runner.

Shared by the `smoke` and `restore rehearsal` jobs.

    docker compose exec -T backend python3 - < .github/scripts/render-sample-referto.py
"""
from PIL import Image, ImageDraw, ImageFont

LINES = [
    "Laboratorio Analisi Cliniche",
    "Referto di esami ematochimici",
    "",
    "Paziente: Mario Rossi",
    "Data prelievo: 14/03/2024",
    "",
    "EMOCROMO COMPLETO",
    "Globuli rossi        4.85   milioni/uL",
    "Emoglobina          14.2    g/dL",
    "Ematocrito          43.1    %",
    "Globuli bianchi      6.30   migliaia/uL",
    "PIASTRINE            245    migliaia/uL",
    "",
    "Colesterolo totale   192    mg/dL",
    "Glicemia              89    mg/dL",
]

# DejaVu ships with the image (the tesseract packages pull it in). Pillow's
# scalable built-in font is the fallback so a slimmer base image cannot break
# this step - the *bitmap* default font is far too small to OCR reliably, which
# is why load_default(size=...) is used.
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
except OSError:
    font = ImageFont.load_default(size=34)

img = Image.new("RGB", (1240, 60 + 46 * len(LINES)), "white")
draw = ImageDraw.Draw(img)
for i, line in enumerate(LINES):
    draw.text((50, 30 + 46 * i), line, fill="black", font=font)
img.save("/tmp/ocr-sample.png")
print("rendered /tmp/ocr-sample.png", img.size)
