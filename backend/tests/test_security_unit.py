"""Behavioural contract for app.auth.security. No database required.

This file is the regression net for two planned dependency swaps:

  1. python-jose  ->  PyJWT
  2. bcrypt 4.x   ->  bcrypt 5.x

It must therefore pass *identically* before and after both swaps. That imposes a
hard rule on everything below: assert only on **observable behaviour** of the
three public helpers - hash/verify roundtrip, accept/reject, expiry - never on

  * exact token strings (the `exp` claim makes them time-dependent anyway),
  * library exception types (`jose.JWTError` will not exist afterwards),
  * library internals (`jwt.get_unverified_claims`, `jose.jws`, ...),
  * bcrypt cost factors or error messages.

Where a claim inside a token has to be inspected, it is decoded here with plain
stdlib base64+json (`_unverified_claims`) rather than via the JWT library: the
compact JWS wire format is a standard shared by both libraries, so that stays
true across the migration while any library call would not.
"""

import base64
import json
import time

import pytest

from app.auth import security
from app.auth.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

# A bcrypt hash of PASSWORD below, generated with bcrypt 4.1.3 and frozen here on
# purpose. Real user rows in Postgres contain hashes of exactly this vintage, so
# if a bcrypt bump ever stopped verifying them every existing account would be
# locked out. This constant is the canary for that.
LEGACY_BCRYPT_4_HASH = "$2b$12$QpY69od.aNjqLz93c7uAMuX.b24AxrWg4oF6PNZ3Nf36lVgm0Y.ZG"
LEGACY_PASSWORD = "docarchive-legacy-password"

PASSWORD = "correct horse battery staple"


def _unverified_claims(token: str) -> dict:
    """Decode a compact JWS payload with stdlib only (no signature check).

    Deliberately library-agnostic - see the module docstring.
    """
    payload_b64 = token.split(".")[1]
    padding = "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64 + padding))


def _live_settings():
    """The Settings instance `security` actually reads.

    `security.py` does `from app.config import settings`, which binds the object,
    not the module attribute. Patching through this accessor keeps the tests
    correct even if something else rebinds `app.config.settings` to a fresh
    instance (conftest's `client` fixture does exactly that).
    """
    return security.settings


# ---------------------------------------------------------------------------
# hash_password
# ---------------------------------------------------------------------------


def test_hash_password_returns_a_string_that_is_not_the_plaintext():
    hashed = hash_password(PASSWORD)

    assert isinstance(hashed, str)
    assert hashed != PASSWORD
    assert PASSWORD not in hashed


def test_hash_password_emits_bcrypt_modular_crypt_format():
    # Pins the on-disk format rather than the cost factor: bcrypt 5 is free to
    # change the default rounds, but if it ever changed the scheme prefix the
    # hashes already stored in the DB would become unverifiable.
    hashed = hash_password(PASSWORD)

    assert hashed.startswith("$2")
    assert len(hashed) == 60


def test_hash_password_is_salted_so_two_hashes_of_one_password_differ():
    first = hash_password(PASSWORD)
    second = hash_password(PASSWORD)

    assert first != second
    # ...and both are still valid: different salt, same password.
    assert verify_password(PASSWORD, first)
    assert verify_password(PASSWORD, second)


# ---------------------------------------------------------------------------
# verify_password
# ---------------------------------------------------------------------------


def test_verify_password_accepts_the_correct_password():
    assert verify_password(PASSWORD, hash_password(PASSWORD)) is True


@pytest.mark.parametrize(
    "wrong",
    [
        "wrong password entirely",
        "Correct horse battery staple",  # capitalisation matters
        "correct horse battery staple ",  # trailing space matters
        "correct horse battery stapl",  # truncated
        "",  # empty must never be a wildcard
    ],
    ids=["different", "case", "trailing-space", "truncated", "empty"],
)
def test_verify_password_rejects_wrong_passwords(wrong):
    assert verify_password(wrong, hash_password(PASSWORD)) is False


def test_verify_password_handles_an_empty_password_symmetrically():
    # An empty password is hashable and only matches itself. Guards against a
    # future `if not password: return True`-shaped mistake.
    hashed = hash_password("")

    assert verify_password("", hashed) is True
    assert verify_password("x", hashed) is False


@pytest.mark.parametrize(
    "not_a_hash",
    [
        "",
        "not-a-bcrypt-hash",
        "plaintext-password-stored-by-mistake",
        "$2b$",
        "x" * 60,
        "pbkdf2_sha256$260000$abc$def",  # a Django hash, i.e. wrong scheme
    ],
    ids=["empty", "garbage", "plaintext", "prefix-only", "right-length", "other-scheme"],
)
def test_verify_password_returns_false_for_a_non_bcrypt_hash(not_a_hash):
    # Pins the `except ValueError: return False` branch in verify_password: a
    # corrupt or foreign password_hash column must fail the login, not 500 it.
    #
    # KNOWN GAP, deliberately not asserted here: a value that *looks* like bcrypt
    # but is truncated (e.g. "$2b$12$short") makes bcrypt 4.1.3's Rust extension
    # panic with pyo3_runtime.PanicException, which inherits from BaseException
    # and so slips straight past `except ValueError`. Asserting that would tie
    # this file to a bcrypt version, which is precisely what it must survive.
    assert verify_password(PASSWORD, not_a_hash) is False


def test_verify_password_still_accepts_a_hash_produced_by_bcrypt_4():
    # The bcrypt 4 -> 5 canary. See LEGACY_BCRYPT_4_HASH above.
    assert verify_password(LEGACY_PASSWORD, LEGACY_BCRYPT_4_HASH) is True
    assert verify_password("wrong", LEGACY_BCRYPT_4_HASH) is False


# ---------------------------------------------------------------------------
# The deliberate 72-byte truncation in _to_bytes
# ---------------------------------------------------------------------------


def test_passwords_are_truncated_at_72_bytes():
    """Accepted bcrypt tradeoff, documented in security._to_bytes.

    bcrypt hashes at most the first 72 bytes of the password. _to_bytes performs
    that cut explicitly (rather than letting bcrypt decide, since bcrypt >= 4.1
    is stricter about over-long input), which means the tail beyond byte 72 is
    security-irrelevant: a 200-char password is exactly as strong as its 72-byte
    prefix. This is a known and accepted property, not a regression - but it is
    asserted so nobody "fixes" the truncation without noticing that it changes
    which passwords validate.
    """
    long_password = "P" * 72 + "-this-tail-is-ignored-entirely"
    prefix = long_password.encode("utf-8")[:72].decode("utf-8")
    assert len(prefix.encode("utf-8")) == 72

    hashed = hash_password(long_password)

    assert verify_password(long_password, hashed) is True
    assert verify_password(prefix, hashed) is True
    # Two passwords sharing only the first 72 bytes are interchangeable.
    assert verify_password(prefix + "-a-completely-different-tail", hashed) is True
    # ...but a difference *inside* the first 72 bytes is still caught.
    assert verify_password("Q" + prefix[1:], hashed) is False


def test_multibyte_password_survives_byte_slicing_mid_character():
    """[:72] slices *bytes*, so it can cut a multibyte character in half.

    "a" + 40 x U+00E9 is 81 bytes, and byte 72 lands between the two bytes of the
    36th "e-acute", so the truncated value is not valid UTF-8. bcrypt takes raw
    bytes and does not care, but any refactor that decodes the slice back to str
    would blow up with UnicodeDecodeError - hence this test.
    """
    password = "a" + "é" * 40
    raw = password.encode("utf-8")
    assert len(raw) == 81
    with pytest.raises(UnicodeDecodeError):
        raw[:72].decode("utf-8")  # confirms the fixture really does split a char

    hashed = hash_password(password)  # must not raise

    assert verify_password(password, hashed) is True
    # Differences *within* the first 72 bytes are still caught. Note that
    # "a" + 39 x e-acute would verify True: at 79 bytes it shares the same
    # 72-byte prefix, which is the truncation property asserted above.
    assert verify_password("b" + "é" * 40, hashed) is False
    assert verify_password("a" + "é" * 30, hashed) is False  # only 61 bytes


def test_short_non_ascii_password_roundtrips():
    password = "pässwörd-àèìòù-éèê"
    assert verify_password(password, hash_password(password)) is True


# ---------------------------------------------------------------------------
# create_access_token / decode_access_token
# ---------------------------------------------------------------------------


def test_create_access_token_returns_a_compact_jws_string():
    token = create_access_token(1)

    # PyJWT 1.x returned bytes; PyJWT >= 2 returns str, as python-jose does.
    # Anything that reaches an Authorization header must be str.
    assert isinstance(token, str)
    assert token.count(".") == 2
    assert all(token.split("."))  # no empty segment


def test_roundtrip_returns_the_subject_as_a_string():
    # The payload is built as {"sub": str(subject)}: an int user id comes back as
    # a str, and every caller must keep coercing before comparing to a DB id.
    assert decode_access_token(create_access_token(7)) == "7"


@pytest.mark.parametrize(
    "subject, expected",
    [
        (7, "7"),
        (0, "0"),  # falsy id must not be lost
        (1234567890, "1234567890"),
        ("42", "42"),  # already a str: unchanged
    ],
    ids=["int", "zero", "big-int", "str"],
)
def test_roundtrip_coerces_every_subject_to_str(subject, expected):
    decoded = decode_access_token(create_access_token(subject))

    assert isinstance(decoded, str)
    assert decoded == expected


def test_token_carries_sub_and_a_numeric_exp_in_the_configured_window():
    minutes = _live_settings().access_token_expire_minutes
    before = time.time()
    token = create_access_token(5)

    claims = _unverified_claims(token)

    assert claims["sub"] == "5"
    # NumericDate: seconds since the epoch, as an int, per RFC 7519.
    assert isinstance(claims["exp"], int)
    expected = before + minutes * 60
    assert expected - 60 <= claims["exp"] <= expected + 60


def test_tokens_for_different_subjects_differ():
    assert create_access_token(1) != create_access_token(2)


def test_tampered_signature_is_rejected():
    header, payload, signature = create_access_token(7).split(".")
    # Flip one character of the signature, keeping it base64url-legal.
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]

    assert decode_access_token(f"{header}.{payload}.{flipped}") is None


def test_tampered_payload_is_rejected():
    # The classic privilege-escalation attempt: rewrite sub, keep the signature.
    header, _payload, signature = create_access_token(7).split(".")
    forged = base64.urlsafe_b64encode(json.dumps({"sub": "1", "exp": 9999999999}).encode())
    forged_payload = forged.decode().rstrip("=")

    assert decode_access_token(f"{header}.{forged_payload}.{signature}") is None


def test_token_signed_with_a_different_secret_is_rejected(monkeypatch):
    settings = _live_settings()
    genuine = create_access_token(7)

    # Both directions: a foreign-signed token must not validate under our secret,
    # and ours must not validate under a foreign secret.
    monkeypatch.setattr(settings, "jwt_secret", "a-completely-different-secret-value")
    foreign = create_access_token(7)
    assert decode_access_token(genuine) is None

    monkeypatch.undo()
    assert decode_access_token(foreign) is None
    # Sanity check that undo() really restored the secret, so the assertion above
    # cannot pass for the wrong reason.
    assert decode_access_token(genuine) == "7"


def test_expired_token_is_rejected(monkeypatch):
    # create_access_token reads settings.access_token_expire_minutes at call
    # time, so a negative value mints an already-expired token without sleeping.
    monkeypatch.setattr(_live_settings(), "access_token_expire_minutes", -10)
    expired = create_access_token(7)
    monkeypatch.undo()

    assert _unverified_claims(expired)["exp"] < time.time()
    assert decode_access_token(expired) is None
    # A freshly minted token still works, i.e. expiry is what was rejected.
    assert decode_access_token(create_access_token(7)) == "7"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "garbage",
        "a.b.c",
        "...",
        "not.a.jwt",
        "eyJhbGciOiJIUzI1NiJ9",  # header only
        "x" * 500,
        "null",
    ],
    ids=[
        "empty",
        "whitespace",
        "garbage",
        "three-junk-segments",
        "dots-only",
        "wordy",
        "header-only",
        "long",
        "json-null",
    ],
)
def test_malformed_tokens_decode_to_none_without_raising(bad):
    assert decode_access_token(bad) is None


@pytest.mark.parametrize("mangle", ["truncate", "prefix", "suffix", "drop-segment"])
def test_mangled_real_tokens_decode_to_none(mangle):
    token = create_access_token(7)
    mangled = {
        "truncate": token[:-6],
        "prefix": "Bearer " + token,  # the header value, not the token
        "suffix": token + "x",
        "drop-segment": token.rsplit(".", 1)[0],
    }[mangle]

    assert decode_access_token(mangled) is None
