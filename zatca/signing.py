"""Cryptographic stamp (XAdES B-B, enveloped) and Phase 2 QR — Security Features
Implementation Standards v1.2 §2.3.3 and §4.

Still to confirm against ZATCA's SDK / sandbox (developer portal not reachable
when this was written — see the overnight notes): the curve (ZATCA_CURVE),
whether SignatureValue is computed over the invoice hash (done here, as the
standard defines the stamp as "the technical digital signature of the hash of
the document") and SigningCertificate (v1) vs SigningCertificateV2.
"""

import base64
import datetime as dt
import hashlib
from dataclasses import dataclass

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


def _signed_properties(qualifying, cert, signing_time):
    props = _el(qualifying, "xades:SignedProperties", Id="xadesSignedProperties")
    signature_props = _el(props, "xades:SignedSignatureProperties")
    _el(signature_props, "xades:SigningTime", signing_time)
    cert_ref = _el(_el(signature_props, "xades:SigningCertificate"), "xades:Cert")
    digest = _el(cert_ref, "xades:CertDigest")
    _el(digest, "ds:DigestMethod", Algorithm=SHA256)
    _el(digest, "ds:DigestValue", _b64(hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).digest()))
    serial = _el(cert_ref, "xades:IssuerSerial")
    _el(serial, "ds:X509IssuerName", cert.issuer.rfc4514_string())
    _el(serial, "ds:X509SerialNumber", str(cert.serial_number))
    return props


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
    props_digest = _el(props_ref, "ds:DigestValue", "")

    _el(signature, "ds:SignatureValue", signature_value)
    _el(_el(_el(signature, "ds:KeyInfo"), "ds:X509Data"), "ds:X509Certificate",
        _b64(cert.public_bytes(serialization.Encoding.DER)))
    qualifying = _el(_el(signature, "ds:Object"), "xades:QualifyingProperties", Target="signature")
    props = _signed_properties(qualifying, cert, signing_time)
    return extensions, props, props_digest


def _qr_timestamp(root) -> str:
    issue_date = root.findtext(_q("cbc:IssueDate"))
    issue_time = root.findtext(_q("cbc:IssueTime"))
    local = timezone.make_aware(dt.datetime.fromisoformat(f"{issue_date}T{issue_time}"))
    return local.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    _extensions, props, props_digest = _signature_block(root, digest_b64, _b64(signature), cert, stamp)
    # Digest of the SignedProperties in their final place (inherited namespaces included).
    props_digest.text = _b64(hashlib.sha256(etree.tostring(props, method="c14n")).digest())

    payload = phase2_qr(
        seller_name=root.findtext("cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName",
                                  namespaces=NS),
        vat_number=root.findtext("cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID",
                                 namespaces=NS),
        timestamp=_qr_timestamp(root),
        total=root.findtext("cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount", namespaces=NS),
        vat_total=root.findtext("cac:TaxTotal/cbc:TaxAmount", namespaces=NS),
        invoice_hash=digest_b64,
        signature=signature,
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
    props = root.xpath("//xades:SignedProperties", namespaces=NS)
    props_ref = root.xpath("//ds:Reference[@URI='#xadesSignedProperties']/ds:DigestValue", namespaces=NS)
    if not props or not props_ref or props_ref[0].text != _b64(
            hashlib.sha256(etree.tostring(props[0], method="c14n")).digest()):
        problems.append("Signed properties digest does not match.")
    qr = root.xpath("cac:AdditionalDocumentReference[cbc:ID='QR']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject",
                    namespaces=NS)
    if not qr or decode_tlv(qr[0].text).get(6) != base64.b64decode(actual):
        problems.append("QR code does not carry the invoice hash.")
    return problems
