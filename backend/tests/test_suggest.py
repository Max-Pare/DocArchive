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


# ---------------------------------------------------------------------------
# guess_date on a real referto layout
#
# Reported from actual use: an exam was filed under the patient's date of birth.
# Italian referti put the patient block - name, date of birth, codice fiscale -
# above the exam itself, so "the first plausible date" is structurally the wrong
# answer, not an unlucky one.
# ---------------------------------------------------------------------------

REFERTO = """\
OSPEDALE SAN RAFFAELE - Laboratorio Analisi
Paziente: ROSSI MARIO
Nato il 12/05/1961 a Milano
Codice Fiscale: RSSMRA61E12F205X

REFERTO DI ESAME EMOCROMOCITOMETRICO
Data prelievo: 14/03/2023
Data refertazione: 15/03/2023

Emoglobina 14.2 g/dL
"""


def test_guess_date_ignores_the_date_of_birth():
    assert guess_date(REFERTO) == date(2023, 3, 14)


def test_guess_date_ignores_the_date_of_birth_when_written_out():
    text = "Paziente: Rossi Mario\nData di nascita: 3 giugno 1958\nEseguito il 7 aprile 2024\n"
    assert guess_date(text) == date(2024, 4, 7)


def test_guess_date_prefers_a_labelled_event_date_over_an_unlabelled_one():
    text = "Stampato 20/03/2023\nData esame: 14/03/2023\n"
    assert guess_date(text) == date(2023, 3, 14)


def test_guess_date_falls_back_to_the_most_recent_past_date():
    """No labels at all: the exam cannot predate the birth, so the later one wins."""
    text = "Rossi Mario 12/05/1961\nEcografia addome completo\n14/03/2023\n"
    assert guess_date(text) == date(2023, 3, 14)


def test_guess_date_ignores_a_future_follow_up_appointment():
    future = date.today().replace(year=date.today().year + 1)
    text = f"Visita del 10/01/2024\nProssimo controllo: {future.strftime('%d/%m/%Y')}\n"
    assert guess_date(text) == date(2024, 1, 10)


def test_guess_date_still_works_when_the_only_date_is_a_birth_date():
    """Better a birth date the user can correct than no suggestion at all."""
    assert guess_date("Tessera sanitaria - nato il 12/05/1961") == date(1961, 5, 12)


def test_guess_visit_type_blood_test():
    assert guess_visit_type_key("Esito EMOCROMO completo e glicemia") == "blood_test"


def test_guess_visit_type_position_breaks_a_tie():
    # Two exams named with equal weight: one keyword each, so the earlier wins.
    text = "Ecografia addome; in allegato anche radiografia torace"
    assert guess_visit_type_key(text) == "ultrasound"


def test_guess_visit_type_none():
    assert guess_visit_type_key("documento generico senza parole chiave") is None


# ---------------------------------------------------------------------------
# guess_visit_type_key: "referto" must not shadow the actual examination
#
# Almost every Italian medical document is headed REFERTO, so ranking that
# keyword alongside the specific ones collapsed nearly everything to `report`.
# ---------------------------------------------------------------------------


def test_the_referto_heading_does_not_shadow_the_exam():
    text = "REFERTO DI ESAME EMOCROMOCITOMETRICO\nGlicemia 95 mg/dL\nPrelievo del 14/03/2023"
    assert guess_visit_type_key(text) == "blood_test"


def test_a_compound_exam_name_still_matches_its_keyword():
    """'emocromo' has to match 'emocromocitometrico' - that is how referti name it."""
    assert guess_visit_type_key("Esame emocromocitometrico completo") == "blood_test"


def test_report_still_wins_when_nothing_specific_is_present():
    assert guess_visit_type_key("Referto di visita specialistica") == "report"


def test_more_matching_keywords_beats_appearing_earlier():
    # "radiografia" comes first, but the blood panel names three of its keywords.
    text = "Allegata radiografia. Esame: emocromo, glicemia, colesterolo."
    assert guess_visit_type_key(text) == "blood_test"


def test_a_short_abbreviation_does_not_match_inside_a_word():
    """'tac' used to fire on 'contatto'; it must not fire on 'tachicardia' either."""
    assert guess_visit_type_key("Riscontrata tachicardia sinusale") is None
    assert guess_visit_type_key("TAC torace con contrasto") == "ct_scan"


def test_suggest_tags_dedup_and_limit():
    tags = suggest_tags("emocromo emocromo glicemia radiografia", limit=6)
    assert "emocromo" in tags
    assert "glicemia" in tags
    assert len(tags) == len(set(tags))


def test_suggest_tags_does_not_match_inside_an_unrelated_word():
    assert suggest_tags("paziente in contatto con il medico curante") == []


def test_suggest_tags_spends_the_limit_on_specific_terms_first():
    text = "REFERTO - esame emocromo, glicemia, colesterolo, prelievo eseguito"
    tags = suggest_tags(text, limit=3)

    assert "referto" not in tags  # generic, ranked last
    assert len(tags) == 3
