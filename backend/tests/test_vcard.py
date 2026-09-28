"""Contact cards from phones (iPhone 3.0, Android 2.1 and 4.0), read strictly."""

import base64

import pytest

from app.services import vcard

IPHONE = (
    b"BEGIN:VCARD\r\nVERSION:3.0\r\nPRODID:-//Apple Inc.//iPhone OS 18//EN\r\n"
    b"N:Pipes;Dave;;;\r\nFN:Dave Pipes\r\nORG:Pipes & Co;\r\n"
    b"item1.TEL;type=pref:+1 555-0100\r\nEMAIL;type=INTERNET;type=HOME:dave@example.com\r\n"
    b"item2.URL:www.davepipes.example\r\nNOTE:Emergency calls\\, weekends too\\nAsk for Sue\r\n"
    b"PHOTO;ENCODING=b;TYPE=JPEG:" + base64.b64encode(b"\xff\xd8\xff\xe0 fake jpeg") + b"\r\n"
    b"END:VCARD\r\n"
)


def test_an_iphone_card() -> None:
    card = vcard.parse(IPHONE)
    assert card.name == "Dave Pipes"
    assert card.company == "Pipes & Co"
    assert (card.phone, card.email) == ("+1 555-0100", "dave@example.com")
    assert card.website == "https://www.davepipes.example"
    assert card.notes == "Emergency calls, weekends too\nAsk for Sue"
    assert card.photo == b"\xff\xd8\xff\xe0 fake jpeg"


def test_an_old_android_card_with_quoted_printable_and_folding() -> None:
    data = (
        "BEGIN:VCARD\nVERSION:2.1\nN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:Tremblay;Ren=C3=A9\n"
        "TEL;CELL:555-0199\nNOTE;ENCODING=QUOTED-PRINTABLE:Line one=0D=0ALine =\ntwo\n"
        "PHOTO;JPEG;ENCODING=BASE64:\n " + base64.b64encode(b"img").decode() + "\n\nEND:VCARD\n"
    ).encode()
    card = vcard.parse(data)
    assert card.name == "René Tremblay"
    assert card.phone == "555-0199"
    assert card.notes == "Line one\r\nLine two"
    assert card.photo == b"img"


def test_vcard_4_with_a_data_photo_and_only_the_first_card() -> None:
    data = (
        b"BEGIN:VCARD\nVERSION:4.0\nFN:Sue\nPHOTO:data:image/png;base64,"
        + base64.b64encode(b"png")
        + b"\nEND:VCARD\nBEGIN:VCARD\nFN:Someone else\nEND:VCARD\n"
    )
    card = vcard.parse(data)
    assert (card.name, card.photo) == ("Sue", b"png")


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "ftp://example.com/x",
        "file:///etc/passwd",
        "data:text/html,<script>",
        "http://exa mple.com",
    ],
)
def test_only_web_addresses_are_kept(url: str) -> None:
    card = vcard.parse(f"BEGIN:VCARD\nFN:X\nURL:{url}\nEND:VCARD\n".encode())
    assert card.website == ""


def test_a_photo_link_is_never_fetched() -> None:
    data = b"BEGIN:VCARD\nFN:X\nPHOTO;VALUE=uri:https://tracker.example/p.jpg\nEND:VCARD\n"
    assert vcard.parse(data).photo is None


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"hello", "isn't a contact card"),
        (b"BEGIN:VCARD\nTEL:1\nEND:VCARD\n", "no name"),
        (b"x" * (vcard.MAX_BYTES + 1), "too large"),
        (b"BEGIN:VCARD\n" + b"NOTE:x\n" * (vcard.MAX_LINES + 1), "too long"),
    ],
)
def test_refused(data: bytes, message: str) -> None:
    with pytest.raises(vcard.VCardError, match=message):
        vcard.parse(data)


def test_long_values_are_cut_to_the_contact_limits() -> None:
    card = vcard.parse(b"BEGIN:VCARD\nFN:" + b"A" * 500 + b"\nTEL:" + b"1" * 90 + b"\nEND:VCARD\n")
    assert (len(card.name), len(card.phone)) == (200, 50)


def test_written_cards_read_back() -> None:
    card = vcard.Card(
        name="Dave Pipes",
        company="Pipes; & Co",
        phone="555-0100",
        email="dave@example.com",
        website="https://www.davepipes.example",
        notes="Line one\nLine, two" + " long" * 30,
        photo=b"\xff\xd8" * 100,
    )
    text = vcard.build(card)
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    assert "N:Pipes;Dave;;;" in text
    assert vcard.parse(text.encode()) == card
