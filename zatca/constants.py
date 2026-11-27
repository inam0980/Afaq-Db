"""Values fixed by ZATCA's published standards (v1.2, 2023-05-19).

Sources (official, zatca.gov.sa → E-Invoicing → Systems Developers):
* Electronic Invoice XML Implementation Standard (BR-KSA rules, code lists)
* Electronic Invoice Security Features Implementation Standards (hash, XAdES, QR)
"""

NS = {
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    "sig": "urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2",
    "sac": "urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2",
    "sbc": "urn:oasis:names:specification:ubl:schema:xsd:SignatureBasicComponents-2",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "xades": "http://uri.etsi.org/01903/v1.3.2#",
}

# BR-KSA-26: previous invoice hash of the very first invoice (base64 of the hex SHA-256 of "0").
FIRST_PIH = "NWZlY2ViNjZmZmM4NmYzOGQ5NTI3ODZjNmQ2OTZjNzljMmRiYzIzOWRkNGU5MWI0NjcyOWQ3M2EyN2ZiNTdlOQ=="

PROFILE_ID = "reporting:1.0"                                   # BR-KSA-EN16931-01
CURRENCY = "SAR"                                               # BR-KSA-EN16931-02

# BT-3 invoice type codes and KSA-2 transaction codes (§11.2.1, BR-KSA-06).
TYPE_CODE_INVOICE = "388"
TYPE_CODE_CREDIT_NOTE = "381"
TRANSACTION_STANDARD = "0100000"
TRANSACTION_SIMPLIFIED = "0200000"

SIGNATURE_ID = "urn:oasis:names:specification:ubl:signature:Invoice"          # BR-KSA-29
SIGNATURE_INFO_ID = "urn:oasis:names:specification:ubl:signature:1"           # BR-KSA-28
SIGNATURE_METHOD = "urn:oasis:names:specification:ubl:dsig:enveloped:xades"   # BR-KSA-30

C14N11 = "http://www.w3.org/2006/12/xml-c14n11"
XPATH_TRANSFORM = "http://www.w3.org/TR/1999/REC-xpath-19991116"
HASH_TRANSFORMS = (
    "not(//ancestor-or-self::ext:UBLExtensions)",
    "not(//ancestor-or-self::cac:Signature)",
    "not(//ancestor-or-self::cac:AdditionalDocumentReference[cbc:ID='QR'])",
)
SIGNED_PROPERTIES_TYPE = "http://www.w3.org/2000/09/xmldsig#SignatureProperties"   # as in the official SDK samples
ECDSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256"
SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"

# §11.2.4: zero-rated (Z) exemption reason codes and their English text.
ZERO_RATE_REASONS = {
    "VATEX-SA-32": "Export of goods",
    "VATEX-SA-33": "Export of services",
    "VATEX-SA-34-1": "The international transport of Goods",
    "VATEX-SA-34-2": "international transport of passengers",
    "VATEX-SA-34-3": "services directly connected and incidental to a Supply of international passenger transport",
    "VATEX-SA-34-4": "Supply of a qualifying means of transport",
    "VATEX-SA-34-5": "Any services relating to Goods or passenger transportation, as defined in article twenty five of these Regulations",
    "VATEX-SA-35": "Medicines and medical equipment",
    "VATEX-SA-36": "Qualifying metals",
    "VATEX-SA-EDU": "Private education to citizen",
    "VATEX-SA-HEA": "Private healthcare to citizen",
    "VATEX-SA-MLTRY": "supply of qualified military goods",
}
