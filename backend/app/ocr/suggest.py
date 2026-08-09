"""Lightweight field guessing from OCR text (Italian medical documents).

Produces *suggestions* only — the user always confirms/edits. No ML, just
regex for dates and keyword matching for visit type + tags.
"""
import re
from datetime import date
from functools import cache

# Italian visit-type keywords -> visit_type.key
#
# The trailing spaces that used to disambiguate "rx " and "rm " are gone: matching
# is word-aware now (see _keyword_pattern), so they are no longer needed.
VISIT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "blood_test": [
        "emocromo", "esame del sangue", "esami ematici", "prelievo",
        "analisi del sangue", "glicemia", "colesterolo", "ematochimici",
    ],
    "xray": ["radiografia", "rx", "raggi x", "radiogramma"],
    "ct_scan": ["tac", "tomografia computerizzata", "tomografia assiale"],
    "mri": ["risonanza magnetica", "rmn", "rm"],
    "ultrasound": ["ecografia", "ecografico", "ecodoppler", "eco addome"],
    "ecg": ["elettrocardiogramma", "ecg", "holter"],
    "report": ["referto", "relazione clinica", "visita specialistica", "lettera di dimissione"],
    "prescription": ["prescrizione", "ricetta", "impegnativa", "piano terapeutico"],
    "vaccination": ["vaccino", "vaccinazione", "certificato vaccinale"],
}

# "report" is the shape of the document, not the kind of examination. Nearly every
# Italian medical document is headed "REFERTO", so ranking it alongside the others
# let it shadow whatever the document is actually about. It is now a fallback,
# consulted only when nothing more specific matched.
_GENERIC_KEYS = frozenset({"report"})

# Below this length a keyword must match as a whole word; at or above it, a leading
# word boundary is enough. Both halves matter: "tac" as a prefix would fire on
# "tachicardia", while "emocromo" as a whole word would MISS
# "emocromocitometrico", which is how the exam is actually named on a referto.
_WHOLE_WORD_MAX_LEN = 3

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


@cache
def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Word-aware matcher for one keyword.

    Plain substring matching produced false positives that read as nonsense to a
    user: "tac" fired on "contatto", "ecg" on any token containing it. A leading
    word boundary fixes those. Short abbreviations get a trailing boundary too,
    otherwise "tac" still fires on "tachicardia".
    """
    escaped = re.escape(keyword)
    if len(keyword) <= _WHOLE_WORD_MAX_LEN:
        return re.compile(rf"\b{escaped}\b", re.IGNORECASE)
    return re.compile(rf"\b{escaped}", re.IGNORECASE)


def _matches(text: str, keywords: list[str]) -> tuple[int, int] | None:
    """(distinct keywords hit, offset of the earliest hit), or None if nothing hit."""
    hits, first = 0, None
    for keyword in keywords:
        found = _keyword_pattern(keyword).search(text)
        if found:
            hits += 1
            first = found.start() if first is None else min(first, found.start())
    return None if first is None else (hits, first)


def guess_visit_type_key(text: str) -> str | None:
    """Which kind of examination the document is about.

    Used to return whichever keyword appeared earliest in the text, which meant the
    "REFERTO" heading at the top beat the exam named below it, and almost every
    document was suggested as a generic report. Ranking now is:

      1. specific types before the generic "report" bucket;
      2. among those, the type with the most distinct keywords present - a blood
         panel says emocromo AND glicemia AND prelievo, a passing mention says one;
      3. ties broken by whichever appeared first, which is the old behaviour and
         still the right answer when two exams are named with equal weight.
    """
    scored: list[tuple[int, int, str]] = []
    for key, keywords in VISIT_TYPE_KEYWORDS.items():
        if key in _GENERIC_KEYS:
            continue
        found = _matches(text, keywords)
        if found:
            hits, position = found
            scored.append((-hits, position, key))
    if scored:
        return min(scored)[2]

    for key in _GENERIC_KEYS:
        if _matches(text, VISIT_TYPE_KEYWORDS[key]):
            return key
    return None


def suggest_tags(text: str, limit: int = 6) -> list[str]:
    """Cheap keyword tags: matched visit-type synonyms present in the text.

    Same word-aware matching as the visit type, so a document mentioning "contatto"
    no longer gets tagged "tac". Generic keywords are ordered last rather than
    dropped - "referto" is a fair tag, just not a useful one to spend the limit on
    when the document also says "emocromo".
    """
    specific: list[str] = []
    generic: list[str] = []
    for key, keywords in VISIT_TYPE_KEYWORDS.items():
        bucket = generic if key in _GENERIC_KEYS else specific
        for keyword in keywords:
            if _keyword_pattern(keyword).search(text) and keyword not in bucket:
                bucket.append(keyword)
    return (specific + generic)[:limit]
