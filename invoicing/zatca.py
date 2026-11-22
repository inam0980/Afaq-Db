"""ZATCA e-invoicing Phase 1 (generation) helpers: the QR code.

The QR carries five TLV (tag-length-value) fields, base64-encoded:
  1 seller name, 2 seller VAT number, 3 invoice timestamp (UTC, ISO 8601),
  4 invoice total incl. VAT, 5 VAT total.
"""

import base64
import datetime as dt
import io
from decimal import Decimal

import qrcode
import qrcode.image.svg

from core.money import money


def tlv(tag: int, value: str) -> bytes:
    data = value.encode("utf-8")
    if len(data) > 255:
        raise ValueError(f"TLV value for tag {tag} is longer than 255 bytes.")
    return bytes([tag, len(data)]) + data


def qr_payload(
    *, seller_name: str, vat_number: str, timestamp: dt.datetime, total: Decimal, vat_total: Decimal
) -> str:
    stamp = timestamp.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw = b"".join(
        [
            tlv(1, seller_name),
            tlv(2, vat_number),
            tlv(3, stamp),
            tlv(4, f"{money(total):.2f}"),
            tlv(5, f"{money(vat_total):.2f}"),
        ]
    )
    return base64.b64encode(raw).decode("ascii")


def qr_svg(payload: str) -> str:
    """Inline SVG (no image library needed) for printing on the invoice."""
    image = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode("utf-8")
