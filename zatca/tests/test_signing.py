"""Unit tests: XAdES signature, Phase 2 QR and demo certificate (Security Features standard §2.3.3, §4)."""

import base64
import hashlib
import re

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from lxml import etree

from customers.tests.factories import BusinessCustomerFactory, CustomerFactory
from invoicing.tests.factories import issued_invoice
from zatca import signing
from zatca.constants import FIRST_PIH, NS
from zatca.hashing import invoice_hash
from zatca.qr import decode_tlv
from zatca.xml_builder import build_invoice

pytestmark = pytest.mark.django_db


@pytest.fixture(scope="module")
def keys():
    key_pem = signing.generate_private_key("secp256k1")
    cert_pem = signing.demo_certificate(key_pem, common_name="AFAQ-EGS-DEMO", vat_number="399999999900003")
    return key_pem, cert_pem


def signed(invoice, keys):
    key_pem, cert_pem = keys
    root = build_invoice(invoice, uuid="3cf5ee18-ee25-44ea-a444-2c37ba7f28be", icv=1, pih=FIRST_PIH)
    return signing.sign_invoice(root, key_pem, cert_pem, simplified=invoice.invoice_type == "simplified")


def ds(root, path):
    return root.xpath(path, namespaces=NS)


def test_private_key_uses_the_configured_curve():
    key = serialization.load_pem_private_key(signing.generate_private_key("secp256r1").encode(), None)
    assert isinstance(key.curve, ec.SECP256R1)
    key = serialization.load_pem_private_key(signing.generate_private_key("secp256k1").encode(), None)
    assert isinstance(key.curve, ec.SECP256K1)
    with pytest.raises(ValueError):
        signing.generate_private_key("rsa")


def test_demo_certificate_is_marked_and_matches_the_key(keys):
    key_pem, cert_pem = keys
    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    key = serialization.load_pem_private_key(key_pem.encode(), None)
    assert cert.public_key().public_numbers() == key.public_key().public_numbers()
    assert "DEMO" in cert.subject.rfc4514_string() and "NOT ISSUED BY ZATCA" in cert.issuer.rfc4514_string()


def test_signature_block_structure(keys):
    result = signed(issued_invoice(customer=BusinessCustomerFactory()), keys)
    root = result.root
    ext = "ext:UBLExtensions/ext:UBLExtension/"
    assert ds(root, ext + "ext:ExtensionURI")[0].text == "urn:oasis:names:specification:ubl:dsig:enveloped:xades"
    info = ext + "ext:ExtensionContent/sig:UBLDocumentSignatures/sac:SignatureInformation/"
    assert ds(root, info + "cbc:ID")[0].text == "urn:oasis:names:specification:ubl:signature:1"
    assert ds(root, info + "sbc:ReferencedSignatureID")[0].text == "urn:oasis:names:specification:ubl:signature:Invoice"
    sig = info + "ds:Signature/"
    assert ds(root, sig + "ds:SignedInfo/ds:SignatureMethod/@Algorithm")[0] == "http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256"
    transforms = ds(root, sig + "ds:SignedInfo/ds:Reference[@Id='invoiceSignedData']/ds:Transforms/ds:Transform")
    assert [t.findtext(f"{{{NS['ds']}}}XPath") for t in transforms[:3]] == [
        "not(//ancestor-or-self::ext:UBLExtensions)",
        "not(//ancestor-or-self::cac:Signature)",
        "not(//ancestor-or-self::cac:AdditionalDocumentReference[cbc:ID='QR'])",
    ]
    assert transforms[3].get("Algorithm") == "http://www.w3.org/2006/12/xml-c14n11"
    props_ref = ds(root, sig + "ds:SignedInfo/ds:Reference[@Type='http://www.w3.org/2000/09/xmldsig#SignatureProperties']")
    assert props_ref and props_ref[0].get("URI") == "#xadesSignedProperties"
    # the UBLExtensions block must come first in the invoice
    assert root[0].tag == f"{{{NS['ext']}}}UBLExtensions"


def test_invoice_digest_is_the_invoice_hash(keys):
    result = signed(issued_invoice(customer=BusinessCustomerFactory()), keys)
    digest = ds(result.root, "//ds:Reference[@Id='invoiceSignedData']/ds:DigestValue")[0].text
    assert digest == result.invoice_hash == invoice_hash(result.root)       # signing does not change the hash


def test_signature_verifies_with_the_certificate(keys):
    result = signed(issued_invoice(customer=BusinessCustomerFactory()), keys)
    cert = x509.load_pem_x509_certificate(keys[1].encode())
    value = base64.b64decode(ds(result.root, "//ds:SignatureValue")[0].text)
    cert.public_key().verify(value, base64.b64decode(result.invoice_hash), ec.ECDSA(hashes.SHA256()))
    embedded = ds(result.root, "//ds:X509Certificate")[0].text
    assert base64.b64decode(embedded) == cert.public_bytes(serialization.Encoding.DER)


def hex_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).hexdigest().encode()).decode()


def test_signed_properties_digest_and_certificate_digest(keys):
    result = signed(issued_invoice(customer=BusinessCustomerFactory()), keys)
    # The SDK hashes the SignedProperties text as written, with xades declared on it and ds on each ds element.
    text = result.xml.decode()
    start = text.index("<xades:SignedProperties ")
    block = text[start:text.index("</xades:SignedProperties>") + len("</xades:SignedProperties>")]
    assert block.startswith('<xades:SignedProperties Id="xadesSignedProperties">')
    declared = block.replace("<xades:SignedProperties ", f'<xades:SignedProperties xmlns:xades="{NS["xades"]}" ', 1)
    declared = re.sub(r"<ds:(\w+)", lambda m: f'<ds:{m.group(1)} xmlns:ds="{NS["ds"]}"', declared)
    ref = ds(result.root, "//ds:Reference[@URI='#xadesSignedProperties']/ds:DigestValue")[0].text
    assert ref == hex_b64(declared.encode())
    cert = x509.load_pem_x509_certificate(keys[1].encode())
    props = ds(result.root, "//xades:SignedProperties")[0]
    cert_digest = ds(props, ".//xades:CertDigest/ds:DigestValue")[0].text
    assert cert_digest == hex_b64(base64.b64encode(cert.public_bytes(serialization.Encoding.DER)))
    assert ds(props, ".//ds:X509SerialNumber")[0].text == str(cert.serial_number)
    assert ds(props, ".//ds:X509IssuerName")[0].text == ", ".join(
        rdn.rfc4514_string() for rdn in reversed(cert.issuer.rdns))


def test_qr_carries_hash_signature_and_key(keys):
    inv = issued_invoice(customer=BusinessCustomerFactory())
    result = signed(inv, keys)
    qr = ds(result.root, "cac:AdditionalDocumentReference[cbc:ID='QR']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject")[0].text
    assert qr == result.qr
    fields = decode_tlv(qr)
    assert fields[2] == b"399999999900003"
    assert fields[4] == f"{inv.total:.2f}".encode() and fields[5] == f"{inv.vat_amount:.2f}".encode()
    assert fields[3] == f"{inv.issue_date:%Y-%m-%d}T{ds(result.root, 'cbc:IssueTime')[0].text}".encode()
    assert fields[6] == result.invoice_hash.encode()                       # base64 text, as in the SDK
    assert fields[7] == ds(result.root, "//ds:SignatureValue")[0].text.encode()
    cert = x509.load_pem_x509_certificate(keys[1].encode())
    assert fields[8] == cert.public_key().public_bytes(serialization.Encoding.DER,
                                                        serialization.PublicFormat.SubjectPublicKeyInfo)
    assert 9 not in fields                                  # standard invoice


def test_qr_reference_sits_between_pih_and_signature(keys):
    root = signed(issued_invoice(customer=BusinessCustomerFactory()), keys).root
    order = [el.tag.split("}")[1] + ":" + (el.findtext(f"{{{NS['cbc']}}}ID") or "") for el in root
             if el.tag.endswith(("AdditionalDocumentReference", "}Signature"))]
    assert order == ["AdditionalDocumentReference:ICV", "AdditionalDocumentReference:PIH",
                     "AdditionalDocumentReference:QR",
                     "Signature:urn:oasis:names:specification:ubl:signature:Invoice"]


def test_simplified_qr_has_the_certificate_signature(keys):
    result = signed(issued_invoice(customer=CustomerFactory()), keys)
    cert = x509.load_pem_x509_certificate(keys[1].encode())
    assert decode_tlv(result.qr)[9] == cert.signature


def test_verify_detects_tampering(keys):
    result = signed(issued_invoice(customer=BusinessCustomerFactory()), keys)
    assert signing.verify(result.xml, keys[1]) == []
    tampered = result.xml.replace(b"<cbc:PayableAmount currencyID=\"SAR\">1150.00", b"<cbc:PayableAmount currencyID=\"SAR\">1.00")
    assert tampered != result.xml
    problems = signing.verify(tampered, keys[1])
    assert problems[0].startswith("Invoice hash does not match the signed digest")


def test_verify_detects_a_bad_signature(keys):
    result = signed(issued_invoice(customer=BusinessCustomerFactory()), keys)
    other_key = signing.generate_private_key("secp256k1")
    other_cert = signing.demo_certificate(other_key, common_name="X", vat_number="399999999900003")
    assert any("signature" in p for p in signing.verify(result.xml, other_cert))


def test_signed_xml_uses_the_standard_prefixes_only(keys):
    xml = signed(issued_invoice(customer=BusinessCustomerFactory()), keys).xml
    assert b"ns0" not in xml and b"xmlns:ns" not in xml
    for prefix in (b"cac:", b"cbc:", b"ext:", b"sig:", b"sac:", b"sbc:", b"ds:", b"xades:"):
        assert prefix in xml


def test_verify_detects_a_replaced_qr(keys):
    result = signed(issued_invoice(customer=BusinessCustomerFactory()), keys)
    tampered = result.xml.replace(result.qr.encode(), b"AQRBRkFR")
    assert signing.verify(tampered, keys[1]) == ["QR code does not carry the invoice hash."]


def test_verify_detects_changed_signed_properties(keys):
    result = signed(issued_invoice(customer=BusinessCustomerFactory()), keys)
    stamp = ds(result.root, "//xades:SigningTime")[0].text.encode()
    tampered = result.xml.replace(stamp, b"2000-01-01T00:00:00")
    assert signing.verify(tampered, keys[1]) == ["Signed properties digest does not match."]


def test_verify_detects_a_changed_certificate_digest(keys):
    result = signed(issued_invoice(customer=BusinessCustomerFactory()), keys)
    digest = ds(result.root, "//xades:CertDigest/ds:DigestValue")[0].text.encode()
    tampered = result.xml.replace(digest, base64.b64encode(b"0" * 64))
    assert signing.verify(tampered, keys[1]) == ["Signed properties digest does not match.",
                                                 "Certificate digest does not match the certificate."]


def test_verify_reports_missing_signed_properties(keys):
    result = signed(issued_invoice(customer=BusinessCustomerFactory()), keys)
    stripped = re.sub(rb"<ds:X509SerialNumber>.*?</ds:X509SerialNumber>", b"", result.xml)
    assert "Signed properties digest does not match." in signing.verify(stripped, keys[1])


def test_signed_properties_escape_special_characters():
    text = signing.signed_properties_xml(signing_time="t", cert_digest="d", issuer="O=A & B <x>", serial="1")
    assert "<ds:X509IssuerName>O=A &amp; B &lt;x&gt;</ds:X509IssuerName>" in text
    assert "xmlns" not in text
    declared = signing.signed_properties_xml(signing_time="t", cert_digest="d", issuer="i", serial="1", declare=True)
    assert declared.startswith('<xades:SignedProperties xmlns:xades="http://uri.etsi.org/01903/v1.3.2#" Id=')
    assert declared.count('xmlns:ds="http://www.w3.org/2000/09/xmldsig#"') == 4
