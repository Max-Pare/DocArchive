"""End-to-end API tests: auth, upload, owner isolation, search filters.

Skipped automatically unless TEST_DATABASE_URL points at a reachable Postgres.
Image OCR is monkeypatched so tesseract is not required to run these.
"""

import io
from urllib.parse import quote

import pytest

from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, requires_db

# Sourced from conftest so the seeded admin and the login attempt can never drift.
ADMIN = {"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD}

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d4944415478da6360000002000154a24f5c0000000049454e44ae426082"
)


def _token(client, creds):
    r = client.post("/auth/login", data=creds)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(autouse=True)
def _no_real_ocr(monkeypatch):
    # Avoid needing tesseract in unit tests: stub the pipeline.
    monkeypatch.setattr(
        "app.ocr.service.extract_text",
        lambda data, mime: "Referto del 14/03/2023 EMOCROMO completo glicemia",
    )


@requires_db
def test_login_and_me(client):
    tok = _token(client, ADMIN)
    r = client.get("/auth/me", headers=_auth(tok))
    assert r.json()["email"] == ADMIN_EMAIL
    assert r.json()["is_admin"] is True


@requires_db
def test_login_bad_password(client):
    r = client.post("/auth/login", data={"username": "admin@example.com", "password": "wrong"})
    assert r.status_code == 401


@pytest.mark.slow
@requires_db
def test_login_is_rate_limited(client):
    """The one test that opts out of the autouse limiter kill-switch.

    Without this the 10/minute limit on /auth/login has no coverage at all, and the
    --proxy-headers flag in entrypoint.sh (which is what makes the limit per-IP
    rather than one global bucket behind Caddy) would be protecting nothing.
    """
    from app.rate_limit import limiter

    limiter.reset()
    limiter.enabled = True

    wrong = {"username": ADMIN_EMAIL, "password": "wrong"}
    codes = [client.post("/auth/login", data=wrong).status_code for _ in range(11)]

    assert codes[:10] == [401] * 10, codes
    assert codes[10] == 429, codes


@requires_db
def test_admin_creates_user_and_owner_isolation(client):
    admin_tok = _token(client, ADMIN)
    # create two regular users
    for email in ("a@fam.it", "b@fam.it"):
        r = client.post(
            "/auth/users",
            headers=_auth(admin_tok),
            json={"email": email, "password": "password123"},
        )
        assert r.status_code == 201, r.text

    tok_a = _token(client, {"username": "a@fam.it", "password": "password123"})
    tok_b = _token(client, {"username": "b@fam.it", "password": "password123"})

    # user A uploads a doc
    r = client.post(
        "/documents",
        headers=_auth(tok_a),
        files={"file": ("scan.png", io.BytesIO(PNG_1x1), "image/png")},
    )
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]

    # A sees it
    assert any(d["id"] == doc_id for d in client.get("/documents", headers=_auth(tok_a)).json())
    # B does NOT see it
    assert all(d["id"] != doc_id for d in client.get("/documents", headers=_auth(tok_b)).json())
    # B cannot fetch it directly
    assert client.get(f"/documents/{doc_id}", headers=_auth(tok_b)).status_code == 404


@requires_db
def test_upload_ocr_suggest_and_search(client):
    admin_tok = _token(client, ADMIN)
    r = client.post(
        "/documents",
        headers=_auth(admin_tok),
        files={"file": ("esami.png", io.BytesIO(PNG_1x1), "image/png")},
    )
    doc_id = r.json()["id"]

    # OCR + suggestions
    r = client.post(f"/documents/{doc_id}/ocr", headers=_auth(admin_tok))
    assert r.status_code == 200, r.text
    sug = r.json()
    assert sug["doc_date"] == "2023-03-14"
    # The stub text is "Referto del 14/03/2023 EMOCROMO completo glicemia". This
    # assertion read "report" until the suggestion rework: guess_visit_type_key
    # ranked by keyword position, so the "Referto" heading that tops nearly every
    # Italian medical document shadowed whatever the document was actually about.
    # "report" is now a fallback bucket, consulted only when nothing specific hits.
    assert sug["visit_type_key"] == "blood_test"
    assert sug["status"] == "ocr_done"

    # full-text search should find it by an OCR'd word
    r = client.get("/documents", headers=_auth(admin_tok), params={"q": "emocromo"})
    assert any(d["id"] == doc_id for d in r.json())

    # filter by visit type
    vt = next(
        v
        for v in client.get("/visit_types", headers=_auth(admin_tok)).json()
        if v["key"] == "blood_test"
    )
    client.patch(
        f"/documents/{doc_id}",
        headers=_auth(admin_tok),
        json={"visit_type_id": vt["id"], "doc_date": "2023-03-14"},
    )
    r = client.get("/documents", headers=_auth(admin_tok), params={"visit_type_id": vt["id"]})
    assert any(d["id"] == doc_id for d in r.json())


@requires_db
def test_download_roundtrip(client):
    admin_tok = _token(client, ADMIN)
    r = client.post(
        "/documents",
        headers=_auth(admin_tok),
        files={"file": ("scan.png", io.BytesIO(PNG_1x1), "image/png")},
    )
    doc_id = r.json()["id"]
    r = client.get(f"/documents/{doc_id}/file", headers=_auth(admin_tok))
    assert r.status_code == 200
    assert r.content == PNG_1x1  # decrypted bytes match original upload


@requires_db
@pytest.mark.parametrize(
    "uploaded_name",
    [
        'evil".png',  # would end the quoted-string early
        "evil\r\nX-Injected: yes.png",  # would inject a header
        "referto ecografia.png",  # ordinary name, must survive intact
        "esame_martedì.png",  # non-ASCII, must survive via filename*
    ],
)
def test_download_content_disposition_survives_a_hostile_filename(client, uploaded_name):
    """End-to-end shape check. The hostile strings are exercised directly against
    _content_disposition() in tests/test_download_headers.py, because the multipart
    encoder percent-encodes the filename before the server ever sees it."""
    admin_tok = _token(client, ADMIN)
    r = client.post(
        "/documents",
        headers=_auth(admin_tok),
        files={"file": (uploaded_name, io.BytesIO(PNG_1x1), "image/png")},
    )
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    stored_name = r.json()["original_filename"]

    r = client.get(f"/documents/{doc_id}/file", headers=_auth(admin_tok))
    assert r.status_code == 200
    disposition = r.headers["content-disposition"]

    # No control characters and no stray quote, so nothing can escape the parameter
    # or start a header of its own.
    assert "\r" not in disposition and "\n" not in disposition
    assert disposition.count('"') == 2
    assert "x-injected" not in {k.lower() for k in r.headers}

    # The stored name still reaches the client, percent-encoded, per RFC 6266.
    assert f"filename*=UTF-8''{quote(stored_name, safe='')}" in disposition
