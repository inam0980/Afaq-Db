"""Invoice hash (XML standard BR-KSA-26; security standard §2.3.3 and §3):

1. remove ext:UBLExtensions, cac:AdditionalDocumentReference[cbc:ID='QR'] and cac:Signature
2. canonicalise (C14N 1.1)  3. SHA-256  4. base64.

lxml implements C14N 1.0; for these documents (no xml:id / xml:base / xml:space
attributes, which is where 1.1 differs) the output is byte-for-byte the same.
"""

import base64
import copy
import hashlib

from lxml import etree

from zatca.constants import NS


def canonical_for_hash(root) -> bytes:
    doc = copy.deepcopy(root)
    removed = (
        doc.xpath("ext:UBLExtensions", namespaces=NS)
        + doc.xpath("cac:Signature", namespaces=NS)
        + doc.xpath("cac:AdditionalDocumentReference[cbc:ID='QR']", namespaces=NS)
    )
    for element in removed:
        parent = element.getparent()
        _drop_keeping_tail(parent, element)
    return etree.tostring(doc, method="c14n")


def _drop_keeping_tail(parent, element):
    """Remove an element; its trailing whitespace stays with the previous node."""
    tail = element.tail
    previous = element.getprevious()
    if tail:
        if previous is not None:
            previous.tail = (previous.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
    parent.remove(element)


def hash_bytes(root) -> bytes:
    return hashlib.sha256(canonical_for_hash(root)).digest()


def invoice_hash(root) -> str:
    return base64.b64encode(hash_bytes(root)).decode("ascii")
