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

# How far back to look for a label describing the date that follows it. Wide enough
# for "data di esecuzione dell'esame:" and for a label sitting in the previous table
# cell, narrow enough not to reach the previous field's value.
_LABEL_WINDOW = 40

# Labels that mean "this is the patient, not the event". A referto states the date of
# birth in its header, above the exam date, which is exactly why taking the first
# plausible date picked the wrong one.
_BIRTH_LABELS = (
    "data di nascita", "data nascita", "nato il", "nata il", "nato/a il", "nat. il",
    "nascita", "d.n.", "dob",
)

# Labels that mean "this IS the event date". Listed because a referto often carries
# several dates - accepted, collected, reported, printed - and these are the ones
# worth preferring over a bare date with no label at all.
_EVENT_LABELS = (
    "data esame", "data dell'esame", "data di esecuzione", "data esecuzione",
    "eseguito il", "eseguita il", "effettuato il", "effettuata il",
    "data prelievo", "data del prelievo", "prelievo del", "prelevato il",
    "data referto", "data del referto", "refertato il", "data accettazione",
    "data di accettazione", "accettazione del", "data ricovero", "visita del",
    "in data",
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


def _candidates(text: str) -> list[tuple[date, int]]:
    """Every plausible date in the text, as (date, start offset), document order."""
    found: list[tuple[date, int]] = []
    for m in _NUMERIC_DATE.finditer(text):
        got = _valid_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if got:
            found.append((got, m.start()))
    for m in _TEXT_DATE.finditer(text):
        got = _valid_date(int(m.group(3)), _IT_MONTHS[m.group(2).lower()], int(m.group(1)))
        if got:
            found.append((got, m.start()))
    found.sort(key=lambda pair: pair[1])
    return found


def _preceding_label(text: str, offset: int) -> str:
    return text[max(0, offset - _LABEL_WINDOW):offset].lower()


def guess_date(text: str) -> date | None:
    """Best guess at the date of the EVENT the document describes.

    This used to return the first plausible date, on the theory that documents lead
    with their event date. Italian referti do not: they lead with the patient, so the
    first date on the page is the date of birth. Reported from real use, where an exam
    was filed under a 1961 date.

    Three passes, cheapest signal last:

      1. drop anything introduced by a birth label;
      2. prefer a date introduced by an event label ("eseguito il", "data prelievo");
      3. otherwise take the most recent date that is not in the future.

    Step 3 leans on an invariant that cannot be violated: a patient cannot be examined
    before being born, so the event date is always the later one. Excluding future
    dates keeps a "prossimo controllo" appointment from beating it.
    """
    candidates = _candidates(text)
    if not candidates:
        return None

    unlabelled_as_birth = [
        (when, pos)
        for when, pos in candidates
        if not any(label in _preceding_label(text, pos) for label in _BIRTH_LABELS)
    ]
    # If every date looked like a birth date, trust the labels less than the text: fall
    # back to the full set rather than returning nothing.
    pool = unlabelled_as_birth or candidates

    labelled = [
        (when, pos)
        for when, pos in pool
        if any(label in _preceding_label(text, pos) for label in _EVENT_LABELS)
    ]
    if labelled:
        return labelled[0][0]

    today = date.today()
    past = [when for when, _ in pool if when <= today]
    if past:
        return max(past)
    return pool[0][0]


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
