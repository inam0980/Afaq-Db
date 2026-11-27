"""Cryptographic stamp (XAdES B-B, enveloped) and Phase 2 QR — Security Features
Implementation Standards v1.2 §2.3.3 and §4.

Formats the standard leaves open are taken from ZATCA's official SDK (Java
238-R3.4.8) and pinned by tests/test_sdk_compat.py against its signed sample:
* curve secp256k1; SignatureValue = ECDSA-SHA256 over the raw invoice hash bytes;
* certificate digest = base64(hex(SHA-256(base64 certificate text)));
* X509IssuerName = the issuer's RDNs most-specific first, joined by ", ";
* SignedProperties digest = base64(hex(SHA-256(text))) over the SignedProperties
  exactly as laid out in the SDK (its indentation, xades declared on the element
  and ds on every ds element) — not a C14N form.
"""

import base64
import datetime as dt
import hashlib
from dataclasses import dataclass
from xml.sax.saxutils import escape

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from django.utils import timezone
from lxml import etree

from zatca.constants import (
    C14N11, ECDSA_SHA256, HASH_TRANSFORMS, NS, SHA256, SIGNATURE_ID, SIGNATURE_INFO_ID, SIGNATURE_METHOD,
    SIGNED_PROPERTIES_TYPE, XPATH_TRANSFORM,
)
from zatca.hashing import hash_bytes, invoice_hash
from zatca.qr import decode_tlv, phase2_qr

CURVES = {"secp256k1": ec.SECP256K1, "secp256r1": ec.SECP256R1}
ORGANIZATION_IDENTIFIER = x509.ObjectIdentifier("2.5.4.97")


def _q(name):
    prefix, local = name.split(":")
    return f"{{{NS[prefix]}}}{local}"


def _el(parent, name, text=None, **attrs):
    element = etree.SubElement(parent, _q(name), attrs)
    if text is not None:
        element.text = text
    return element


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# --- keys and certificates -------------------------------------------------------------

def generate_private_key(curve: str) -> str:
    if curve not in CURVES:
        raise ValueError(f"Unsupported curve {curve!r}; use one of {sorted(CURVES)}.")
    key = ec.generate_private_key(CURVES[curve]())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode("ascii")


def demo_certificate(key_pem: str, *, common_name: str, vat_number: str) -> str:
    """A self-signed certificate for offline demos only. ZATCA issues the real one at onboarding."""
    key = load_key(key_pem)
    name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "SA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "DEMO - NOT ISSUED BY ZATCA"),
        x509.NameAttribute(ORGANIZATION_IDENTIFIER, vat_number),
        x509.NameAttribute(NameOID.COMMON_NAME, f"{common_name} DEMO"),
    ])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def load_key(key_pem: str):
    return serialization.load_pem_private_key(key_pem.encode("ascii"), password=None)


def load_cert(cert_pem: str):
    return x509.load_pem_x509_certificate(cert_pem.encode("ascii"))


# --- signing -------------------------------------------------------------------------------

@dataclass
class SignResult:
    root: object
    xml: bytes
    invoice_hash: str
    qr: str


def _hex_b64(data: bytes) -> str:
    return _b64(hashlib.sha256(data).hexdigest().encode("ascii"))


def certificate_digest(cert_b64: str) -> str:
    return _hex_b64(cert_b64.encode("ascii"))


def issuer_name(cert) -> str:
    return ", ".join(rdn.rfc4514_string() for rdn in reversed(cert.issuer.rdns))


_PROPS_LINES = (
    (0, '<xades:SignedProperties{xades} Id="xadesSignedProperties">'),
    (36, "<xades:SignedSignatureProperties>"),
    (40, "<xades:SigningTime>{signing_time}</xades:SigningTime>"),
    (40, "<xades:SigningCertificate>"),
    (44, "<xades:Cert>"),
    (48, "<xades:CertDigest>"),
    (52, '<ds:DigestMethod{ds} Algorithm="' + SHA256 + '"/>'),
    (52, "<ds:DigestValue{ds}>{cert_digest}</ds:DigestValue>"),
    (48, "</xades:CertDigest>"),
    (48, "<xades:IssuerSerial>"),
    (52, "<ds:X509IssuerName{ds}>{issuer}</ds:X509IssuerName>"),
    (52, "<ds:X509SerialNumber{ds}>{serial}</ds:X509SerialNumber>"),
    (48, "</xades:IssuerSerial>"),
    (44, "</xades:Cert>"),
    (40, "</xades:SigningCertificate>"),
    (36, "</xades:SignedSignatureProperties>"),
    (32, "</xades:SignedProperties>"),
)


def signed_properties_xml(*, signing_time, cert_digest, issuer, serial, declare=False) -> str:
    """The SignedProperties text in the SDK's layout; `declare` adds the namespace declarations it hashes with."""
    template = "\n".join(" " * indent + line for indent, line in _PROPS_LINES)
    return template.format(
        xades=f' xmlns:xades="{NS["xades"]}"' if declare else "",
        ds=f' xmlns:ds="{NS["ds"]}"' if declare else "",
        signing_time=escape(signing_time), cert_digest=escape(cert_digest),
        issuer=escape(issuer), serial=escape(serial))


def signed_properties_digest(**values) -> str:
    return _hex_b64(signed_properties_xml(declare=True, **values).encode("utf-8"))


def _graft(parent, source):
    """Copy `source` under `parent` keeping its text and whitespace; prefixes come from the parent's scope."""
    element = etree.SubElement(parent, source.tag, dict(source.attrib))
    element.text, element.tail = source.text, source.tail
    for child in source:
        _graft(element, child)
    return element


def _signed_properties(qualifying, cert, signing_time):
    values = dict(signing_time=signing_time,
                  cert_digest=certificate_digest(_b64(cert.public_bytes(serialization.Encoding.DER))),
                  issuer=issuer_name(cert), serial=str(cert.serial_number))
    props = _graft(qualifying, etree.fromstring(signed_properties_xml(declare=True, **values)))
    return props, signed_properties_digest(**values)


def _signature_block(root, digest_value, signature_value, cert, signing_time):
    # Created inside the invoice (so ext/cbc prefixes come from the root), then moved to the top.
    extensions = etree.SubElement(root, _q("ext:UBLExtensions"), nsmap={
        "sig": NS["sig"], "sac": NS["sac"], "sbc": NS["sbc"], "ds": NS["ds"], "xades": NS["xades"]})
    root.insert(0, extensions)
    extension = _el(extensions, "ext:UBLExtension")
    _el(extension, "ext:ExtensionURI", SIGNATURE_METHOD)
    documents = _el(_el(extension, "ext:ExtensionContent"), "sig:UBLDocumentSignatures")
    info = _el(documents, "sac:SignatureInformation")
    _el(info, "cbc:ID", SIGNATURE_INFO_ID)
    _el(info, "sbc:ReferencedSignatureID", SIGNATURE_ID)
    signature = _el(info, "ds:Signature", Id="signature")

    signed_info = _el(signature, "ds:SignedInfo")
    _el(signed_info, "ds:CanonicalizationMethod", Algorithm=C14N11)
    _el(signed_info, "ds:SignatureMethod", Algorithm=ECDSA_SHA256)
    invoice_ref = _el(signed_info, "ds:Reference", Id="invoiceSignedData", URI="")
    transforms = _el(invoice_ref, "ds:Transforms")
    for xpath in HASH_TRANSFORMS:
        _el(_el(transforms, "ds:Transform", Algorithm=XPATH_TRANSFORM), "ds:XPath", xpath)
    _el(transforms, "ds:Transform", Algorithm=C14N11)
    _el(invoice_ref, "ds:DigestMethod", Algorithm=SHA256)
    _el(invoice_ref, "ds:DigestValue", digest_value)
    props_ref = _el(signed_info, "ds:Reference", Type=SIGNED_PROPERTIES_TYPE, URI="#xadesSignedProperties")
    _el(props_ref, "ds:DigestMethod", Algorithm=SHA256)
    props_digest = _el(props_ref, "ds:DigestValue")

    _el(signature, "ds:SignatureValue", signature_value)
    _el(_el(_el(signature, "ds:KeyInfo"), "ds:X509Data"), "ds:X509Certificate",
        _b64(cert.public_bytes(serialization.Encoding.DER)))
    qualifying = _el(_el(signature, "ds:Object"), "xades:QualifyingProperties", Target="signature")
    _props, props_digest.text = _signed_properties(qualifying, cert, signing_time)
    return extensions


def _qr_timestamp(root) -> str:
    """Tag 3: the invoice's own IssueDate and IssueTime (as in the SDK sample)."""
    return f"{root.findtext(_q('cbc:IssueDate'))}T{root.findtext(_q('cbc:IssueTime'))}"


def _insert_qr(root, payload):
    reference = etree.SubElement(root, _q("cac:AdditionalDocumentReference"))
    _el(reference, "cbc:ID", "QR")
    _el(_el(reference, "cac:Attachment"), "cbc:EmbeddedDocumentBinaryObject", payload, mimeCode="text/plain")
    pih = root.xpath("cac:AdditionalDocumentReference[cbc:ID='PIH']", namespaces=NS)[0]
    pih.addnext(reference)


def sign_invoice(root, key_pem: str, cert_pem: str, *, simplified: bool, signing_time=None) -> SignResult:
    key, cert = load_key(key_pem), load_cert(cert_pem)
    digest = hash_bytes(root)
    digest_b64 = _b64(digest)
    signature = key.sign(digest, ec.ECDSA(hashes.SHA256()))
    stamp = timezone.localtime(signing_time or timezone.now()).strftime("%Y-%m-%dT%H:%M:%S")

    signature_b64 = _b64(signature)
    _signature_block(root, digest_b64, signature_b64, cert, stamp)

    payload = phase2_qr(
        seller_name=root.findtext("cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName",
                                  namespaces=NS),
        vat_number=root.findtext("cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID",
                                 namespaces=NS),
        timestamp=_qr_timestamp(root),
        total=root.findtext("cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount", namespaces=NS),
        vat_total=root.findtext("cac:TaxTotal/cbc:TaxAmount", namespaces=NS),
        invoice_hash=digest_b64,
        signature=signature_b64,
        public_key=cert.public_key().public_bytes(serialization.Encoding.DER,
                                                  serialization.PublicFormat.SubjectPublicKeyInfo),
        certificate_signature=cert.signature if simplified else None,
    )
    _insert_qr(root, payload)
    xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
    return SignResult(root=root, xml=xml, invoice_hash=digest_b64, qr=payload)


# --- local verification ------------------------------------------------------------------

def verify(xml: bytes, cert_pem: str) -> list[str]:
    """Problems found re-checking a signed invoice (empty list = all good)."""
    root = etree.fromstring(xml)
    cert = load_cert(cert_pem)
    problems = []
    actual = invoice_hash(root)
    signed = root.xpath("//ds:Reference[@Id='invoiceSignedData']/ds:DigestValue", namespaces=NS)
    if not signed or signed[0].text != actual:
        problems.append("Invoice hash does not match the signed digest (the invoice was changed after signing).")
    value = root.xpath("//ds:SignatureValue", namespaces=NS)
    try:
        cert.public_key().verify(base64.b64decode(value[0].text if value else ""),
                                 base64.b64decode(signed[0].text if signed else ""), ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        problems.append("ECDSA signature is not valid for this certificate.")
    found = {name: root.findtext(f".//{_q(tag)}") for name, tag in (
        ("signing_time", "xades:SigningTime"), ("issuer", "ds:X509IssuerName"), ("serial", "ds:X509SerialNumber"))}
    found["cert_digest"] = root.findtext(f".//{_q('xades:CertDigest')}/{_q('ds:DigestValue')}")
    props_ref = root.xpath("//ds:Reference[@URI='#xadesSignedProperties']/ds:DigestValue", namespaces=NS)
    if None in found.values() or not props_ref or props_ref[0].text != signed_properties_digest(**found):
        problems.append("Signed properties digest does not match.")
    if found["cert_digest"] != certificate_digest(_b64(cert.public_bytes(serialization.Encoding.DER))):
        problems.append("Certificate digest does not match the certificate.")
    qr = root.xpath("cac:AdditionalDocumentReference[cbc:ID='QR']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject",
                    namespaces=NS)
    if not qr or decode_tlv(qr[0].text).get(6) != actual.encode("ascii"):
        problems.append("QR code does not carry the invoice hash.")
    return problems
