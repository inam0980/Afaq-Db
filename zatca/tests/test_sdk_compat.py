"""Golden tests: our signing reproduces the values in ZATCA's official SDK sample, which the SDK
validator accepts (see sdk_vectors.py). These pin the exact formats the published standard leaves open."""

import base64

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from zatca import signing
from zatca.qr import decode_tlv, phase2_qr
from zatca.tests import sdk_vectors as sdk


def sample_cert():
    return x509.load_der_x509_certificate(base64.b64decode(sdk.CERTIFICATE))


def test_certificate_digest_is_base64_of_hex_sha256_of_the_base64_certificate():
    assert signing.certificate_digest(sdk.CERTIFICATE) == sdk.CERT_DIGEST


def test_issuer_name_is_written_like_the_sdk():
    assert signing.issuer_name(sample_cert()) == sdk.ISSUER_NAME == "CN=PRZEINVOICESCA4-CA, DC=extgazt, DC=gov, DC=local"


def test_signed_properties_digest_matches_the_sdk_sample():
    digest = signing.signed_properties_digest(
        signing_time=sdk.SIGNING_TIME, cert_digest=sdk.CERT_DIGEST,
        issuer=sdk.ISSUER_NAME, serial=sdk.SERIAL_NUMBER)
    assert digest == sdk.SIGNED_PROPERTIES_DIGEST


def test_signature_is_ecdsa_sha256_over_the_raw_invoice_hash():
    sample_cert().public_key().verify(base64.b64decode(sdk.SIGNATURE_VALUE), base64.b64decode(sdk.INVOICE_HASH),
                                      ec.ECDSA(hashes.SHA256()))


def test_phase2_qr_rebuilds_the_sdk_sample_byte_for_byte():
    fields = decode_tlv(sdk.QR)
    assert fields[3] == b"2022-08-17T17:41:08"          # IssueDate + "T" + IssueTime, as written in the invoice
    rebuilt = phase2_qr(
        seller_name=fields[1].decode(), vat_number=fields[2].decode(), timestamp=fields[3].decode(),
        total=fields[4].decode(), vat_total=fields[5].decode(),
        invoice_hash=sdk.INVOICE_HASH, signature=sdk.SIGNATURE_VALUE,     # tags 6 and 7: base64 text
        public_key=fields[8], certificate_signature=fields[9])             # tags 8 and 9: raw DER bytes
    assert rebuilt == sdk.QR
