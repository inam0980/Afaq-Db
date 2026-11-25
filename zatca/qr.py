"""Phase 2 QR code (Security Features Implementation Standards §4.1).

TLV: one byte tag, one byte length, then the value. Tags 1-5 are UTF-8 text;
tag 6 is the invoice hash as raw SHA-256 bytes (32); tags 7-9 are the raw
bytes of the ECDSA signature, the public key and — for simplified invoices —
the signature of the certificate issued by ZATCA's CA. Base64 of the whole.
"""

import base64


def tlv(tag: int, value) -> bytes:
    data = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    if len(data) > 255:
        raise ValueError(f"TLV value for tag {tag} is longer than 255 bytes.")
    return bytes([tag, len(data)]) + data


def phase2_qr(*, seller_name, vat_number, timestamp, total, vat_total, invoice_hash, signature, public_key,
              certificate_signature=None) -> str:
    fields = [
        tlv(1, seller_name),
        tlv(2, vat_number),
        tlv(3, timestamp),
        tlv(4, total),
        tlv(5, vat_total),
        tlv(6, base64.b64decode(invoice_hash)),
        tlv(7, signature),
        tlv(8, public_key),
    ]
    if certificate_signature is not None:
        fields.append(tlv(9, certificate_signature))
    return base64.b64encode(b"".join(fields)).decode("ascii")


def decode_tlv(payload: str) -> dict[int, bytes]:
    raw = base64.b64decode(payload)
    fields, i = {}, 0
    while i < len(raw):
        tag, length = raw[i], raw[i + 1]
        fields[tag] = raw[i + 2:i + 2 + length]
        i += 2 + length
    return fields
