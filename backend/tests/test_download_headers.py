"""Unit tests for the Content-Disposition builder in app/routers/documents.py.

These call _content_disposition() directly rather than going through an upload,
on purpose. A multipart encoder percent-encodes the filename before it reaches
the server, so an HTTP-level test cannot deliver a raw quote or a raw CRLF into
original_filename. The column is String(512) with no validation, and the value is
only ever defaulted on the way in (documents.py), so nothing stops a future
import tool, bulk load, or non-conforming client from putting one there. That is
the case these cover.
"""
from urllib.parse import quote

import pytest

from app.routers.documents import _content_disposition

HOSTILE = [
    'evil".png',  # would end the quoted-string early
    'evil"; download; filename="pwned.exe',  # ...and append parameters
    "evil\r\nX-Injected: yes.png",  # would inject a whole header
    "evil\nSet-Cookie: a=b.png",  # bare LF is enough for some clients
    "evil\\.png",  # backslash escapes in a quoted-string
    "\x00\x07\x1b[31m.png",  # NUL, BEL, ANSI escape
]

BENIGN = [
    "referto.png",
    "referto ecografia 2023.pdf",
    "esame_martedì.png",
    "экг.pdf",
    "検査.png",
]


@pytest.mark.parametrize("filename", HOSTILE + BENIGN)
def test_header_value_is_always_well_formed(filename):
    value = _content_disposition(filename)

    # Nothing that could terminate the header or start a new one.
    assert "\r" not in value
    assert "\n" not in value
    assert not any(ord(c) < 0x20 or ord(c) == 0x7F for c in value)
    # Exactly one quoted-string: the fallback filename. A third quote would mean
    # the value escaped its own parameter.
    assert value.count('"') == 2
    assert value.startswith('inline; filename="')


@pytest.mark.parametrize("filename", HOSTILE + BENIGN)
def test_the_real_name_is_preserved_in_filename_star(filename):
    """The ASCII fallback is lossy by design; filename* is what clients should use."""
    value = _content_disposition(filename)

    assert f"filename*=UTF-8''{quote(filename, safe='')}" in value


def test_a_name_made_only_of_stripped_characters_falls_back_to_a_default():
    value = _content_disposition("\r\n\x00")

    assert value.startswith('inline; filename="document"')
    # The original is still transmitted faithfully in the encoded parameter.
    assert f"filename*=UTF-8''{quote(chr(13) + chr(10) + chr(0), safe='')}" in value


def test_an_ordinary_name_is_left_alone_in_the_ascii_fallback():
    assert _content_disposition("referto.pdf").startswith('inline; filename="referto.pdf"')
