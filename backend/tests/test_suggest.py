"""Pure-logic tests for OCR field suggestion — no DB, no tesseract needed."""
from datetime import date

from app.ocr.suggest import guess_date, guess_visit_type_key, suggest_tags


def test_guess_date_numeric():
    assert guess_date("Referto del 14/03/2023 ore 10:00") == date(2023, 3, 14)


def test_guess_date_textual_italian():
    assert guess_date("Milano, 5 settembre 2021") == date(2021, 9, 5)


def test_guess_date_rejects_implausible():
    assert guess_date("codice 99/99/9999 pratica") is None


def test_guess_date_none_when_absent():
    assert guess_date("nessuna data qui") is None


def test_guess_visit_type_blood_test():
    assert guess_visit_type_key("Esito EMOCROMO completo e glicemia") == "blood_test"


def test_guess_visit_type_earliest_wins():
    # "ecografia" appears before "radiografia" -> ultrasound wins
    text = "Ecografia addome; in allegato anche radiografia torace"
    assert guess_visit_type_key(text) == "ultrasound"


def test_guess_visit_type_none():
    assert guess_visit_type_key("documento generico senza parole chiave") is None


def test_suggest_tags_dedup_and_limit():
    tags = suggest_tags("emocromo emocromo glicemia radiografia", limit=6)
    assert "emocromo" in tags
    assert "glicemia" in tags
    assert len(tags) == len(set(tags))
