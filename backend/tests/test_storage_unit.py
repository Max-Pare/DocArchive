"""Unit tests for app/storage.py — at-rest encryption, path layout, deletion.

No database and no HTTP client: every test runs against a pytest `tmp_path`
that stands in for STORAGE_DIR.

Two things about the module under test drive the fixture below:

  * `storage.py` does `from app.config import settings`, so it holds a *reference*
    to the Settings instance that existed at import time. Patching an attribute
    ON THAT OBJECT is what actually changes storage's behaviour, which is why the
    fixture patches `app.storage.settings` rather than re-importing app.config.
    (Normally the same object; conftest's `client` fixture rebinds
    `app.config.settings` to a fresh instance, and storage would not see it.)
  * the Fernet instance is memoised in the module global `_fernet`, so it must be
    reset to None whenever the key changes — otherwise a stale cipher silently
    keeps using the previous key.
"""
import base64
import os
import re
import uuid
from pathlib import Path

import pytest
from cryptography.fernet import Fernet, InvalidToken

from tests.conftest import TEST_FERNET_KEY

# stored_path == "<owner_id>/<uuid4().hex>.enc", forward slashes only.
STORED_PATH_RE = re.compile(r"^\d+/[0-9a-f]{32}\.enc$")

OWNER = 7


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    """app.storage, wired to a throwaway STORAGE_DIR with a known key.

    STORAGE_DIR is a *subdirectory* of tmp_path on purpose: the traversal tests
    need a sibling directory that is outside the storage root but still safely
    inside the test's temp area.
    """
    import app.storage as storage_module

    storage_root = tmp_path / "files"
    storage_root.mkdir()
    monkeypatch.setattr(storage_module.settings, "storage_dir", str(storage_root))
    monkeypatch.setattr(storage_module.settings, "file_encryption_key", TEST_FERNET_KEY)
    monkeypatch.setattr(storage_module, "_fernet", None)  # drop any memoised cipher
    return storage_module


@pytest.fixture()
def root(storage) -> Path:
    return Path(storage.settings.storage_dir)


# ---------------------------------------------------------------------------
# save_encrypted: return contract
# ---------------------------------------------------------------------------


def test_save_encrypted_returns_relative_path_and_plaintext_size(storage, root):
    plaintext = b"referto del 14/03/2023"

    rel_path, size = storage.save_encrypted(plaintext, OWNER)

    assert STORED_PATH_RE.match(rel_path), rel_path
    assert rel_path.startswith(f"{OWNER}/")
    assert "\\" not in rel_path  # normalised even on Windows
    assert not os.path.isabs(rel_path)  # relative to storage_dir, never absolute

    # The reported size is the PLAINTEXT length (what the UI shows), not the size
    # of the file on disk. Fernet adds IV + HMAC + base64 expansion, so the two
    # must differ; asserting inequality is what pins "plaintext, not ciphertext".
    assert size == len(plaintext)
    on_disk_size = (root / rel_path).stat().st_size
    assert on_disk_size != size
    assert on_disk_size > size


def test_saved_bytes_are_encrypted_not_plaintext(storage, root):
    plaintext = b"CODICE FISCALE RSSMRA80A01H501U glicemia 92 mg/dL"

    rel_path, _ = storage.save_encrypted(plaintext, OWNER)
    raw = (root / rel_path).read_bytes()

    assert raw != plaintext
    assert plaintext not in raw
    assert b"GLICEMIA" not in raw.upper()
    # Fernet token: leading version byte 0x80 base64s to the "gAAAA" prefix.
    assert raw.startswith(b"gAAAA")
    # ...and the whole token is valid urlsafe base64.
    assert re.fullmatch(rb"[A-Za-z0-9_\-=]+", raw)
    assert base64.urlsafe_b64decode(raw)[0] == 0x80


# ---------------------------------------------------------------------------
# Round trips
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"short", id="small"),
        pytest.param(b"", id="empty"),
        pytest.param(bytes(range(256)) * 4, id="binary-all-byte-values"),
        pytest.param(b"pre\x00\x00post\x00", id="embedded-nulls"),
        pytest.param(b"\xc3\xa8 accento", id="utf8-bytes"),
        pytest.param(os.urandom(1024 * 1024), id="1MiB-random"),
    ],
)
def test_round_trip(storage, payload):
    rel_path, size = storage.save_encrypted(payload, OWNER)

    assert storage.read_decrypted(rel_path) == payload
    assert size == len(payload)


def test_two_saves_for_same_owner_get_distinct_paths(storage, root):
    first_path, _ = storage.save_encrypted(b"first", OWNER)
    second_path, _ = storage.save_encrypted(b"second", OWNER)

    # uuid4 filename: no collision, so the second save cannot clobber the first.
    assert first_path != second_path
    assert os.path.dirname(first_path) == os.path.dirname(second_path) == str(OWNER)
    assert storage.read_decrypted(first_path) == b"first"
    assert storage.read_decrypted(second_path) == b"second"
    assert len(list((root / str(OWNER)).iterdir())) == 2


def test_distinct_owners_get_distinct_subdirectories(storage, root):
    path_a, _ = storage.save_encrypted(b"owner-1 data", 1)
    path_b, _ = storage.save_encrypted(b"owner-2 data", 2)

    assert path_a.startswith("1/")
    assert path_b.startswith("2/")
    assert sorted(p.name for p in root.iterdir()) == ["1", "2"]
    assert storage.read_decrypted(path_a) == b"owner-1 data"
    assert storage.read_decrypted(path_b) == b"owner-2 data"


def test_same_plaintext_twice_yields_different_ciphertext(storage, root):
    """Fernet uses a random IV, so identical documents are not correlatable on disk."""
    payload = b"identical content"
    path_a, _ = storage.save_encrypted(payload, OWNER)
    path_b, _ = storage.save_encrypted(payload, OWNER)

    assert (root / path_a).read_bytes() != (root / path_b).read_bytes()


# ---------------------------------------------------------------------------
# delete_file
# ---------------------------------------------------------------------------


def test_delete_file_removes_the_file_then_is_a_silent_no_op(storage, root):
    rel_path, _ = storage.save_encrypted(b"to be deleted", OWNER)
    abs_path = root / rel_path
    assert abs_path.exists()

    storage.delete_file(rel_path)
    assert not abs_path.exists()

    # delete_file swallows FileNotFoundError, so a second delete must not raise.
    # DELETE /documents/{id} relies on this: a row whose blob already vanished
    # still deletes cleanly instead of 500-ing.
    storage.delete_file(rel_path)
    assert not abs_path.exists()

    # The owner directory itself is intentionally left behind (never cleaned up).
    assert (root / str(OWNER)).is_dir()


def test_delete_file_ignores_a_path_that_never_existed(storage):
    storage.delete_file(f"{OWNER}/{uuid.uuid4().hex}.enc")  # must not raise


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_read_decrypted_missing_file_raises_filenotfounderror(storage):
    """Pins CURRENT behaviour: the error is UNHANDLED.

    read_decrypted() opens the path with no existence check, and
    GET /documents/{id}/file (app/routers/documents.py:160) calls it without a
    try/except, so a document row whose blob is missing from disk — DB restored
    without the volume, half-finished manual cleanup — surfaces to the client as
    an HTTP 500 plus a stack trace in the logs, rather than a 404/410. Mapping
    this onto a real HTTP error is hardening-wave work; until then the test
    documents the raw exception that reaches FastAPI.
    """
    with pytest.raises(FileNotFoundError):
        storage.read_decrypted(f"{OWNER}/{uuid.uuid4().hex}.enc")


def test_get_fernet_raises_runtimeerror_when_key_is_empty(storage, monkeypatch):
    monkeypatch.setattr(storage.settings, "file_encryption_key", "")
    monkeypatch.setattr(storage, "_fernet", None)  # reset BEFORE, or the cache hides it

    with pytest.raises(RuntimeError, match="FILE_ENCRYPTION_KEY is not set"):
        storage._get_fernet()

    # The guard lives in _get_fernet, so both public entry points inherit it.
    with pytest.raises(RuntimeError):
        storage.save_encrypted(b"data", OWNER)


def test_empty_key_is_only_detected_when_the_cipher_is_first_built(storage, monkeypatch):
    """Pins the memoisation: an already-built cipher survives blanking the key.

    Not a security hole (the process keeps using the key it started with), but it
    means a config change made at runtime is invisible until the next restart.
    """
    storage.save_encrypted(b"warms the cache", OWNER)  # populates _fernet
    monkeypatch.setattr(storage.settings, "file_encryption_key", "")

    rel_path, _ = storage.save_encrypted(b"still works", OWNER)  # no RuntimeError
    assert storage.read_decrypted(rel_path) == b"still works"


def test_decrypting_with_the_wrong_key_raises_invalidtoken(storage, monkeypatch):
    """Pins CURRENT behaviour: also UNHANDLED -> HTTP 500.

    Rotating or losing FILE_ENCRYPTION_KEY makes every existing document
    undecryptable, and because read_decrypted() lets InvalidToken propagate,
    GET /documents/{id}/file answers 500 rather than anything diagnosable. Fernet
    supports MultiFernet key rotation; wiring that up, plus a clear error for the
    "wrong key" case, is hardening-wave work.
    """
    rel_path, _ = storage.save_encrypted(b"secret referto", OWNER)

    other_key = Fernet.generate_key().decode()
    assert other_key != TEST_FERNET_KEY
    monkeypatch.setattr(storage.settings, "file_encryption_key", other_key)
    monkeypatch.setattr(storage, "_fernet", None)  # force a rebuild with the new key

    with pytest.raises(InvalidToken):
        storage.read_decrypted(rel_path)


def test_decrypting_tampered_ciphertext_raises_invalidtoken(storage, root):
    """Fernet is authenticated: a flipped byte on disk is detected, not returned."""
    rel_path, _ = storage.save_encrypted(b"integrity matters", OWNER)
    abs_path = root / rel_path

    raw = bytearray(abs_path.read_bytes())
    raw[20] = ord("A") if raw[20] != ord("A") else ord("B")  # stays valid base64
    abs_path.write_bytes(bytes(raw))

    with pytest.raises(InvalidToken):
        storage.read_decrypted(rel_path)


# ---------------------------------------------------------------------------
# SECURITY FINDING (documented, deliberately NOT fixed here)
# ---------------------------------------------------------------------------
#
# read_decrypted() and delete_file() build their target as
#     os.path.join(settings.storage_dir, stored_path)
# with no containment check — no realpath() followed by an "is this still under
# storage_dir?" assertion. Two consequences:
#
#   1. a stored_path containing ".." escapes STORAGE_DIR entirely;
#   2. an ABSOLUTE stored_path discards STORAGE_DIR completely, because
#      os.path.join("/data/files", "/etc/hostname") == "/etc/hostname".
#
# NOT currently exploitable: stored_path is only ever server-generated
# (save_encrypted writes "<owner_id>/<uuid4>.enc") and is never taken from
# request input — the download route looks the row up by id and reads
# doc.stored_path. So today this is defence-in-depth, not a live vulnerability.
#
# It goes live the moment anything writes an attacker-influenced value into
# documents.stored_path: an import/restore tool, a migration from another
# archive, an admin bulk load, or a future endpoint that accepts a path. Since
# delete_file() would then delete arbitrary files and read_decrypted() would read
# them, the hardening wave should add one _resolve(stored_path) helper that
# rejects anything not under storage_dir, and route all three functions through it.
#
# The tests below assert the CURRENT (unsafe) behaviour, so they fail loudly once
# that containment check lands — that failure is the signal to update them.
# Everything they touch stays inside pytest's tmp_path; no real file is harmed.


def test_read_decrypted_traversal_escapes_storage_dir_pending_hardening(storage, tmp_path):
    outside = tmp_path / "outside.enc"  # sibling of storage_dir, NOT under it
    outside.write_bytes(Fernet(TEST_FERNET_KEY.encode()).encrypt(b"data from outside"))

    assert storage.read_decrypted("../outside.enc") == b"data from outside"


def test_read_decrypted_absolute_path_ignores_storage_dir_pending_hardening(storage, tmp_path):
    elsewhere = tmp_path / "elsewhere" / "leak.enc"
    elsewhere.parent.mkdir()
    elsewhere.write_bytes(Fernet(TEST_FERNET_KEY.encode()).encrypt(b"absolute path leak"))

    # os.path.join drops its left operand entirely when the right one is absolute.
    assert os.path.join(storage.settings.storage_dir, str(elsewhere)) == str(elsewhere)
    assert storage.read_decrypted(str(elsewhere)) == b"absolute path leak"


def test_delete_file_traversal_deletes_outside_storage_dir_pending_hardening(storage, tmp_path):
    outside = tmp_path / "victim.txt"
    outside.write_text("a file the archive has no business touching")

    storage.delete_file("../victim.txt")

    assert not outside.exists()  # deleted: there is no containment check
