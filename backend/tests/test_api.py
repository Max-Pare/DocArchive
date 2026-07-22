"""End-to-end API tests: auth, upload, owner isolation, search filters.

Skipped automatically unless TEST_DATABASE_URL points at a reachable Postgres.
Image OCR is monkeypatched so tesseract is not required to run these.
"""
import io

import pytest

from tests.conftest import requires_db

ADMIN = {"username": "admin@example.com", "password": "changeme"}

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
    assert r.json()["email"] == "admin@example.com"
    assert r.json()["is_admin"] is True


@requires_db
def test_login_bad_password(client):
    r = client.post("/auth/login", data={"username": "admin@example.com", "password": "wrong"})
    assert r.status_code == 401


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
    assert sug["visit_type_key"] == "blood_test"
    assert sug["status"] == "ocr_done"

    # full-text search should find it by an OCR'd word
    r = client.get("/documents", headers=_auth(admin_tok), params={"q": "emocromo"})
    assert any(d["id"] == doc_id for d in r.json())

    # filter by visit type
    vt = next(v for v in client.get("/visit_types", headers=_auth(admin_tok)).json()
              if v["key"] == "blood_test")
    client.patch(f"/documents/{doc_id}", headers=_auth(admin_tok),
                 json={"visit_type_id": vt["id"], "doc_date": "2023-03-14"})
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
