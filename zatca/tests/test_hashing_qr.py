"""Unit tests: invoice hash (XML standard BR-KSA-26) and Phase 2 QR TLV (security standard §4)."""

import base64
import hashlib

import pytest
from lxml import etree

from zatca.constants import FIRST_PIH, NS
from zatca.hashing import canonical_for_hash, invoice_hash
from zatca.qr import decode_tlv, phase2_qr, tlv

DOC = f"""<Invoice xmlns="{NS['inv']}" xmlns:cac="{NS['cac']}" xmlns:cbc="{NS['cbc']}" xmlns:ext="{NS['ext']}">
  <ext:UBLExtensions><ext:UBLExtension><ext:ExtensionURI>sig</ext:ExtensionURI></ext:UBLExtension></ext:UBLExtensions>
  <cbc:ID>INV-1</cbc:ID>
  <cac:AdditionalDocumentReference><cbc:ID>ICV</cbc:ID><cbc:UUID>1</cbc:UUID></cac:AdditionalDocumentReference>
  <cac:AdditionalDocumentReference><cbc:ID>QR</cbc:ID><cac:Attachment><cbc:EmbeddedDocumentBinaryObject mimeCode="text/plain">AAA</cbc:EmbeddedDocumentBinaryObject></cac:Attachment></cac:AdditionalDocumentReference>
  <cac:Signature><cbc:ID>urn:oasis:names:specification:ubl:signature:Invoice</cbc:ID></cac:Signature>
  <cbc:Note>hello</cbc:Note>
</Invoice>"""


def parse(text):
    return etree.fromstring(text.encode())


def test_first_previous_hash_is_base64_of_sha256_of_zero():
    assert base64.b64decode(FIRST_PIH).decode() == hashlib.sha256(b"0").hexdigest()


def test_hash_ignores_extensions_qr_and_signature():
    bare = DOC
    for block in (
        "<ext:UBLExtensions><ext:UBLExtension><ext:ExtensionURI>sig</ext:ExtensionURI></ext:UBLExtension></ext:UBLExtensions>",
        '<cac:AdditionalDocumentReference><cbc:ID>QR</cbc:ID><cac:Attachment><cbc:EmbeddedDocumentBinaryObject mimeCode="text/plain">AAA</cbc:EmbeddedDocumentBinaryObject></cac:Attachment></cac:AdditionalDocumentReference>',
        "<cac:Signature><cbc:ID>urn:oasis:names:specification:ubl:signature:Invoice</cbc:ID></cac:Signature>",
    ):
        bare = bare.replace(block, "")
    assert invoice_hash(parse(DOC)) == invoice_hash(parse(bare))


def test_hash_changes_with_content_and_keeps_other_references():
    assert invoice_hash(parse(DOC)) != invoice_hash(parse(DOC.replace("hello", "hellO")))
    canonical = canonical_for_hash(parse(DOC)).decode()
    assert "<cbc:ID>ICV</cbc:ID>" in canonical           # only the QR reference is removed
    assert "UBLExtensions" not in canonical and "Signature" not in canonical and ">QR<" not in canonical


def test_hash_is_base64_sha256_of_canonical_form():
    expected = base64.b64encode(hashlib.sha256(canonical_for_hash(parse(DOC))).digest()).decode()
    assert invoice_hash(parse(DOC)) == expected
    assert len(base64.b64decode(expected)) == 32


def test_hash_does_not_modify_the_document():
    root = parse(DOC)
    invoice_hash(root)
    assert root.find(f"{{{NS['ext']}}}UBLExtensions") is not None


# --- QR ---------------------------------------------------------------------------

def test_tlv_encodes_tag_length_value():
    assert tlv(1, "Afaq") == b"\x01\x04Afaq"
    assert tlv(6, b"\x00" * 32)[:2] == b"\x06\x20"
    assert tlv(1, "آفاق")[1] == 8                         # UTF-8 bytes, not characters
    with pytest.raises(ValueError, match="longer than 255 bytes"):
        tlv(1, "x" * 256)


HASH = base64.b64encode(b"h" * 32).decode()
FIELDS = dict(seller_name="AFAQ", vat_number="300000000000003", timestamp="2026-11-25T10:00:00",
              total="1150.00", vat_total="150.00", invoice_hash=HASH, signature="c2lnLWJ5dGVz",
              public_key=b"pub-key")


def test_phase2_qr_standard_has_tags_1_to_8():
    fields = decode_tlv(phase2_qr(**FIELDS))
    assert sorted(fields) == [1, 2, 3, 4, 5, 6, 7, 8]
    assert fields[1] == b"AFAQ" and fields[4] == b"1150.00" and fields[5] == b"150.00"
    assert fields[6] == HASH.encode()                      # base64 text of the hash (44), as in the SDK
    assert (fields[7], fields[8]) == (b"c2lnLWJ5dGVz", b"pub-key")


def test_phase2_qr_simplified_adds_tag_9():
    fields = decode_tlv(phase2_qr(**FIELDS, certificate_signature=b"ca-sig"))
    assert fields[9] == b"ca-sig"


def test_qr_is_base64_and_within_700_characters():
    payload = phase2_qr(**FIELDS, certificate_signature=b"c" * 72)
    base64.b64decode(payload, validate=True)
    assert len(payload) <= 700
