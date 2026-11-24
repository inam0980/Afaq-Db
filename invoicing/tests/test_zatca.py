"""Unit tests: ZATCA Phase 1 QR payload (TLV, base64) and QR rendering.

Spec (ZATCA e-invoicing, simplified invoices): five TLV fields
  1 seller name, 2 seller VAT number, 3 timestamp, 4 invoice total (incl. VAT),
  5 VAT total. Tag = 1 byte, length = 1 byte (UTF-8 byte length), value = UTF-8.
"""

import base64
import datetime as dt
from decimal import Decimal as D

import pytest

from invoicing.zatca import qr_payload, qr_svg, tlv


def test_tlv_single_field():
    assert tlv(1, "ABC") == bytes([1, 3]) + b"ABC"


def test_tlv_length_counts_utf8_bytes_not_characters():
    arabic = "شركة"                       # 4 characters, 8 bytes in UTF-8
    assert tlv(1, arabic)[:2] == bytes([1, 8])
    assert tlv(1, arabic)[2:].decode("utf-8") == arabic


def test_tlv_rejects_values_longer_than_255_bytes():
    with pytest.raises(ValueError, match="255 bytes"):
        tlv(1, "x" * 256)


def test_payload_matches_spec_layout():
    payload = qr_payload(
        seller_name="Bobs Records",
        vat_number="310122393500003",
        timestamp=dt.datetime(2022, 4, 25, 15, 30, tzinfo=dt.UTC),
        total=D("1000"),
        vat_total=D("150"),
    )
    expected = (
        bytes([1, 12]) + b"Bobs Records"
        + bytes([2, 15]) + b"310122393500003"
        + bytes([3, 20]) + b"2022-04-25T15:30:00Z"
        + bytes([4, 7]) + b"1000.00"
        + bytes([5, 6]) + b"150.00"
    )
    assert base64.b64decode(payload) == expected


def test_timestamp_is_converted_to_utc():
    riyadh = dt.timezone(dt.timedelta(hours=3))
    payload = qr_payload(
        seller_name="A", vat_number="310122393500003",
        timestamp=dt.datetime(2026, 1, 1, 3, 0, tzinfo=riyadh),   # = 00:00 UTC
        total=D("1"), vat_total=D("0"),
    )
    assert b"2026-01-01T00:00:00Z" in base64.b64decode(payload)


def test_qr_svg_is_inline_svg():
    svg = qr_svg("AQxCb2Jz")
    assert svg.lstrip().startswith("<svg") or svg.lstrip().startswith("<?xml")
    assert "</svg>" in svg
