"""Lightweight field guessing from OCR text (Italian medical documents).

Produces *suggestions* only — the user always confirms/edits. No ML, just
regex for dates and keyword matching for visit type + tags.
"""
import re
from datetime import date

# Italian visit-type keywords -> visit_type.key
VISIT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "blood_test": [
        "emocromo", "esame del sangue", "esami ematici", "prelievo",
        "analisi del sangue", "glicemia", "colesterolo", "ematochimici",
    ],
    "xray": ["radiografia", "rx ", "raggi x", "radiogramma"],
    "ct_scan": ["tac", "tomografia computerizzata", "tomografia assiale"],
    "mri": ["risonanza magnetica", "rmn", "rm "],
    "ultrasound": ["ecografia", "ecografico", "ecodoppler", "eco addome"],
    "ecg": ["elettrocardiogramma", "ecg", "holter"],
    "report": ["referto", "relazione clinica", "visita specialistica", "lettera di dimissione"],
    "prescription": ["prescrizione", "ricetta", "impegnativa", "piano terapeutico"],
    "vaccination": ["vaccino", "vaccinazione", "certificato vaccinale"],
}

# Month names (Italian) for textual dates
_IT_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b")
_TEXT_DATE = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(_IT_MONTHS.keys()) + r")\s+(\d{4})\b",
    re.IGNORECASE,
)


def _valid_date(y: int, m: int, d: int) -> date | None:
    if y < 100:
        y += 2000 if y < 70 else 1900
    try:
        result = date(y, m, d)
    except ValueError:
        return None
    # reject implausible future/very old dates
    if result.year < 1950 or result.year > date.today().year + 1:
        return None
    return result


def guess_date(text: str) -> date | None:
    """First plausible date wins (documents usually lead with the event date)."""
    for m in _NUMERIC_DATE.finditer(text):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        got = _valid_date(y, mo, d)
        if got:
            return got
    for m in _TEXT_DATE.finditer(text):
        d = int(m.group(1))
        mo = _IT_MONTHS[m.group(2).lower()]
        y = int(m.group(3))
        got = _valid_date(y, mo, d)
        if got:
            return got
    return None


def guess_visit_type_key(text: str) -> str | None:
    low = text.lower()
    best_key, best_pos = None, None
    for key, words in VISIT_TYPE_KEYWORDS.items():
        for w in words:
            pos = low.find(w)
            if pos != -1 and (best_pos is None or pos < best_pos):
                best_key, best_pos = key, pos
    return best_key


def suggest_tags(text: str, limit: int = 6) -> list[str]:
    """Cheap keyword tags: matched visit-type synonyms present in the text."""
    low = text.lower()
    found: list[str] = []
    for words in VISIT_TYPE_KEYWORDS.values():
        for w in words:
            token = w.strip()
            if token and token in low and token not in found:
                found.append(token)
    return found[:limit]
